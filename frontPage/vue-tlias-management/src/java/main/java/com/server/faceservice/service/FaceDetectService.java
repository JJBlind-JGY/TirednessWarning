package com.server.faceservice.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.utils.ModelWebsocket;
import com.server.faceservice.utils.SafeWebSocketSender;
import jakarta.annotation.PostConstruct;
import org.bytedeco.ffmpeg.global.avutil;
import org.bytedeco.javacv.FFmpegFrameGrabber;
import org.bytedeco.javacv.Frame;
import org.bytedeco.javacv.Java2DFrameConverter;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

@Service
public class FaceDetectService {
    private static final int FRAME_SKIP_INTERVAL = 30;

    @Autowired
    ModelWebsocket modelWebsocket;

    private SafeWebSocketSender sender;
    private final ThreadPoolExecutor frameProcessingExecutor = new ThreadPoolExecutor(
            1,
            2,
            30L,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(2),
            new ThreadPoolExecutor.DiscardOldestPolicy()
    );

    @PostConstruct
    public void init() {
        avutil.av_log_set_level(avutil.AV_LOG_ERROR);
        sender = new SafeWebSocketSender(modelWebsocket);
    }

    public boolean isConnected() {
        return modelWebsocket.isConnected;
    }

    private void sendFrame(byte[] frameData, String userId) {
        String base64Image = Base64.getEncoder().encodeToString(frameData);
        ObjectMapper objectMapper = new ObjectMapper();
        try {
            String jsonMessage = objectMapper.writeValueAsString(Map.of("userId", userId, "frame", base64Image));
            sender.sendAsync(jsonMessage.getBytes());
        } catch (JsonProcessingException e) {
            e.printStackTrace();
        }
    }

    public void processVideo(String rtspUrl, String userId) throws Exception {
        try (FFmpegFrameGrabber grabber = new FFmpegFrameGrabber(rtspUrl)) {
            grabber.setOption("rtsp_transport", "tcp");
            grabber.setOption("fflags", "nobuffer");
            grabber.setOption("flags", "low_delay");
            grabber.setOption("max_delay", "500000");
            grabber.setOption("probesize", "32768");
            grabber.setOption("analyzeduration", "0");
            grabber.setOption("stimeout", "5000000");
            grabber.setOption("buffer_size", "1048576");
            grabber.setVideoOption("autorotate", "1");

            grabber.start();
            if (grabber.grabImage() == null) {
                throw new Exception("Failed to grab the first frame from the video stream.");
            }

            Frame frame;
            int skipped = 0;
            while ((frame = grabber.grabImage()) != null) {
                if (skipped < FRAME_SKIP_INTERVAL) {
                    skipped += 1;
                    continue;
                }
                skipped = 0;

                if (frame.image == null) {
                    continue;
                }

                final Frame finalFrame = frame.clone();
                frameProcessingExecutor.submit(() -> {
                    try {
                        byte[] imageBytes = convertFrameToJpeg(finalFrame);
                        sendFrame(imageBytes, userId);
                    } catch (IOException ignored) {
                    }
                });
            }
        } catch (FFmpegFrameGrabber.Exception e) {
            System.err.println("RTSP Stream Error: " + e.getMessage());
            throw e;
        }
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
        convertedImage.getGraphics().drawImage(image, 0, 0, null);
        return convertedImage;
    }
}
