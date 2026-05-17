package com.server.faceservice.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.utils.ModelWebsocket;
import com.server.faceservice.utils.SafeWebSocketSender;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.bytedeco.ffmpeg.global.avutil;
import org.bytedeco.javacv.FFmpegFrameGrabber;
import org.bytedeco.javacv.Frame;
import org.bytedeco.javacv.Java2DFrameConverter;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import javax.imageio.ImageIO;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.Base64;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class FaceDetectService {
    private static final int FRAME_PROCESSING_THREADS = Math.max(4, Runtime.getRuntime().availableProcessors());
    private static final int EXPORT_FRAME_THREADS = Math.max(2, Runtime.getRuntime().availableProcessors() / 2);

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Map<String, CameraSamplingState> cameraStates = new ConcurrentHashMap<>();

    @Autowired
    private ModelWebsocket modelWebsocket;

    @Autowired
    private SimpMessagingTemplate messagingTemplate;

    @Autowired
    private AbnormalSampleService abnormalSampleService;

    @Value("${websocket.webUser.url:/topic/face_fatigue/}")
    private String faceFatigueUrl;

    @Value("${face.camera.sample-interval-ms:1000}")
    private long sampleIntervalMs;

    private SafeWebSocketSender sender;
    private final ThreadPoolExecutor frameProcessingExecutor = new ThreadPoolExecutor(
            FRAME_PROCESSING_THREADS,
            FRAME_PROCESSING_THREADS,
            30L,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(FRAME_PROCESSING_THREADS * 4),
            new ThreadPoolExecutor.DiscardOldestPolicy()
    );
    private final ThreadPoolExecutor exportFrameExecutor = new ThreadPoolExecutor(
            EXPORT_FRAME_THREADS,
            EXPORT_FRAME_THREADS,
            30L,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(EXPORT_FRAME_THREADS * 8),
            new ThreadPoolExecutor.DiscardOldestPolicy()
    );

    @PostConstruct
    public void init() {
        avutil.av_log_set_level(avutil.AV_LOG_ERROR);
        sender = new SafeWebSocketSender(modelWebsocket);
    }

    @PreDestroy
    public void shutdown() {
        frameProcessingExecutor.shutdownNow();
        exportFrameExecutor.shutdownNow();
    }

    public boolean isConnected() {
        return modelWebsocket.isConnected();
    }

    public void clearCamera(String userId) {
        if (sender != null) {
            sender.clearCamera(userId);
        }
        cameraStates.remove(userId);
    }

    public long getLastFrameSentAt(String userId) {
        return stateFor(userId).lastFrameSentAt.get();
    }

    public Map<String, Object> getCameraMetrics(String userId) {
        CameraSamplingState state = stateFor(userId);
        Map<String, Object> metrics = new HashMap<>(sender.metricsSnapshot(userId));
        metrics.put("framesCaptured", state.framesCaptured.get());
        metrics.put("framesSkipped", state.framesSkipped.get());
        metrics.put("staleTasksDropped", state.staleTasksDropped.get());
        metrics.put("lastCapturedAt", state.lastCapturedAt.get());
        metrics.put("lastFrameAt", Math.max(state.lastFrameSentAt.get(), state.lastCapturedAt.get()));
        return metrics;
    }

    private CameraSamplingState stateFor(String userId) {
        return cameraStates.computeIfAbsent(userId, ignored -> new CameraSamplingState());
    }

    private long nextGeneration(String userId) {
        CameraSamplingState state = stateFor(userId);
        state.lastSampleAt.set(0);
        return state.generation.incrementAndGet();
    }

    private boolean shouldSample(String userId, long now) {
        CameraSamplingState state = stateFor(userId);
        long previous = state.lastSampleAt.get();
        if (previous > 0 && now - previous < sampleIntervalMs) {
            state.framesSkipped.incrementAndGet();
            return false;
        }
        return state.lastSampleAt.compareAndSet(previous, now);
    }

    private void sendFrame(byte[] frameData, String userId) {
        String base64Image = Base64.getEncoder().encodeToString(frameData);
        try {
            String jsonMessage = objectMapper.writeValueAsString(Map.of("userId", userId, "frame", base64Image));
            sender.sendAsync(userId, jsonMessage.getBytes());
            stateFor(userId).lastFrameSentAt.set(System.currentTimeMillis());
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize camera frame payload", e);
        }
    }

    private void publishCameraStatus(String userId, String status, String message) {
        messagingTemplate.convertAndSend(faceFatigueUrl + userId, Map.of(
                "userId", userId,
                "status", status,
                "message", message == null ? "" : message,
                "timestamp", System.currentTimeMillis()
        ));
    }

    public void processVideo(String rtspUrl, String userId) throws Exception {
        long generation = nextGeneration(userId);
        try (FFmpegFrameGrabber grabber = new FFmpegFrameGrabber(rtspUrl)) {
            configureGrabber(grabber);

            grabber.start();
            if (grabber.grabImage() == null) {
                publishCameraStatus(userId, "no_frame", "No frame received from camera.");
                throw new Exception("Failed to grab the first frame from the video stream.");
            }
            publishCameraStatus(userId, "online", "Camera stream connected.");

            Frame frame;
            while (!Thread.currentThread().isInterrupted() && (frame = grabber.grabImage()) != null) {
                if (frame.image == null) {
                    continue;
                }

                long now = System.currentTimeMillis();
                boolean shouldRecordExportFrame = abnormalSampleService.shouldRecordVideoFrame(userId, now);
                boolean shouldSendModelFrame = shouldSample(userId, now);
                if (!shouldRecordExportFrame && !shouldSendModelFrame) {
                    continue;
                }

                if (shouldRecordExportFrame) {
                    final Frame exportFrame = frame.clone();
                    final long exportTimestamp = now;
                    exportFrameExecutor.submit(() -> {
                        CameraSamplingState state = stateFor(userId);
                        if (state.generation.get() != generation) {
                            state.staleTasksDropped.incrementAndGet();
                            return;
                        }
                        try {
                            byte[] imageBytes = convertFrameToJpeg(exportFrame);
                            if (state.generation.get() == generation) {
                                abnormalSampleService.recordVideoFrame(userId, exportTimestamp, imageBytes);
                            } else {
                                state.staleTasksDropped.incrementAndGet();
                            }
                        } catch (IOException ignored) {
                        }
                    });
                }

                if (!shouldSendModelFrame) {
                    continue;
                }

                stateFor(userId).framesCaptured.incrementAndGet();
                stateFor(userId).lastCapturedAt.set(now);
                final Frame modelFrame = frame.clone();
                frameProcessingExecutor.submit(() -> {
                    CameraSamplingState state = stateFor(userId);
                    if (state.generation.get() != generation) {
                        state.staleTasksDropped.incrementAndGet();
                        return;
                    }
                    try {
                        byte[] imageBytes = convertFrameToJpeg(modelFrame);
                        if (state.generation.get() == generation) {
                            sendFrame(imageBytes, userId);
                        } else {
                            state.staleTasksDropped.incrementAndGet();
                        }
                    } catch (IOException ignored) {
                    }
                });
            }
            publishCameraStatus(userId, "offline", "Camera stream ended.");
        } catch (FFmpegFrameGrabber.Exception e) {
            publishCameraStatus(userId, "offline", e.getMessage());
            System.err.println("RTSP Stream Error: " + e.getMessage());
            throw e;
        }
    }

    private void configureGrabber(FFmpegFrameGrabber grabber) {
        grabber.setOption("rtsp_transport", "tcp");
        grabber.setOption("fflags", "nobuffer");
        grabber.setOption("flags", "low_delay");
        grabber.setOption("max_delay", "500000");
        grabber.setOption("probesize", "32768");
        grabber.setOption("analyzeduration", "0");
        // RTSP/socket 超时: 不同 FFmpeg 版本命名不一，多塞几个兼容名，目的是卡死时能 5s 超时返回让上层自动重连
        grabber.setOption("stimeout", "5000000");   // FFmpeg <=5.0 RTSP demuxer private option
        grabber.setOption("rw_timeout", "5000000"); // FFmpeg 5.1+ generic IO option
        grabber.setOption("timeout", "5000000");    // 部分版本的 fallback
        grabber.setOption("buffer_size", "1048576");
        grabber.setVideoOption("autorotate", "1");
    }

    @SuppressWarnings("all")
    private byte[] convertFrameToJpeg(Frame frame) throws IOException {
        Java2DFrameConverter converter = new Java2DFrameConverter();
        BufferedImage image = converter.getBufferedImage(frame);

        if (isDeprecatedPixelFormat(image)) {
            image = convertToModernFormat(image);
        }

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        ImageIO.write(image, "jpg", baos);
        return baos.toByteArray();
    }

    private boolean isDeprecatedPixelFormat(BufferedImage image) {
        return image.getType() != BufferedImage.TYPE_3BYTE_BGR &&
                image.getType() != BufferedImage.TYPE_INT_RGB;
    }

    private BufferedImage convertToModernFormat(BufferedImage image) {
        BufferedImage convertedImage = new BufferedImage(
                image.getWidth(),
                image.getHeight(),
                BufferedImage.TYPE_3BYTE_BGR
        );
        Graphics2D graphics = convertedImage.createGraphics();
        try {
            graphics.drawImage(image, 0, 0, null);
        } finally {
            graphics.dispose();
        }
        return convertedImage;
    }

    private static class CameraSamplingState {
        private final AtomicLong generation = new AtomicLong(0);
        private final AtomicLong lastSampleAt = new AtomicLong(0);
        private final AtomicLong lastCapturedAt = new AtomicLong(0);
        private final AtomicLong lastFrameSentAt = new AtomicLong(0);
        private final AtomicLong framesCaptured = new AtomicLong(0);
        private final AtomicLong framesSkipped = new AtomicLong(0);
        private final AtomicLong staleTasksDropped = new AtomicLong(0);
    }
}
