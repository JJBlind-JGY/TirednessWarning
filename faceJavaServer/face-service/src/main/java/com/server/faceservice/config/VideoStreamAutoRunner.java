package com.server.faceservice.config;

import com.server.faceservice.service.CameraConfigService;
import com.server.faceservice.service.FaceDetectService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;

import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

@Component
public class VideoStreamAutoRunner {

    private static final Logger log = LoggerFactory.getLogger(VideoStreamAutoRunner.class);
    private static final long RETRY_DELAY_MS = 5000L;
    private static final int RTSP_PROBE_TIMEOUT_MS = 2000;

    @Autowired
    private FaceDetectService faceDetectService;

    @Autowired
    private CameraConfigService cameraConfigService;

    @Autowired
    private SimpMessagingTemplate messagingTemplate;

    @Value("${websocket.webUser.url:/topic/face_fatigue/}")
    private String faceFatigueUrl;

    private final Map<String, CameraWorker> workers = new ConcurrentHashMap<>();
    private final Map<String, CameraRuntimeStatus> streamStatuses = new ConcurrentHashMap<>();

    @EventListener(ApplicationReadyEvent.class)
    public void startVideoStreamTask() {
        log.info("Application ready, loading camera streams...");
        reloadStreams();
    }

    public synchronized void reloadStreams() {
        Set<String> activeIds = new HashSet<>();
        cameraConfigService.list().stream()
                .forEach(camera -> {
                    activeIds.add(camera.getId());
                    CameraWorker existing = workers.get(camera.getId());
                    if (existing != null && !cameraSourceKey(camera).equals(existing.sourceKey)) {
                        stopCamera(camera.getId());
                    }
                    startCamera(camera);
                });

        workers.keySet().stream()
                .filter(cameraId -> !activeIds.contains(cameraId))
                .toList()
                .forEach(this::stopCamera);
    }

    public synchronized void startCamera(String cameraId, String rtspUrl) {
        startCamera(new CameraConfig(cameraId, cameraId, rtspUrl, cameraId));
    }

    public synchronized void startCamera(CameraConfig camera) {
        String cameraId = camera.getId();
        CameraWorker existing = workers.get(cameraId);
        if (existing != null && existing.isAlive()) {
            return;
        }

        CameraWorker worker = new CameraWorker(camera);
        workers.put(cameraId, worker);
        worker.start();
    }

    public synchronized void stopCamera(String cameraId) {
        CameraWorker worker = workers.remove(cameraId);
        if (worker != null) {
            worker.stop();
        }
        faceDetectService.clearCamera(cameraId);
        publishCameraStatus(cameraId, "offline", "Camera stream stopped.");
    }

    public List<Map<String, Object>> getCameraStatuses() {
        List<Map<String, Object>> statuses = new ArrayList<>();
        cameraConfigService.list().forEach(camera -> {
            CameraRuntimeStatus status = streamStatuses.getOrDefault(camera.getId(), new CameraRuntimeStatus(camera.getId()));
            statuses.add(status.toMap(
                    faceDetectService.isConnected(),
                    faceDetectService.getLastFrameSentAt(camera.getId()),
                    faceDetectService.getCameraMetrics(camera.getId())
            ));
        });
        return statuses;
    }

    private void publishCameraStatus(String cameraId, String status, String message) {
        CameraRuntimeStatus runtimeStatus = streamStatuses.computeIfAbsent(cameraId, CameraRuntimeStatus::new);
        String previous = runtimeStatus.status;
        runtimeStatus.status = status;
        runtimeStatus.message = message == null ? "" : message;
        runtimeStatus.updatedAt = System.currentTimeMillis();
        if ("online".equals(status) || "ok".equals(status)) {
            runtimeStatus.lastFrameAt = runtimeStatus.updatedAt;
        }

        if (status.equals(previous) && !"online".equals(status)) {
            return;
        }
        messagingTemplate.convertAndSend(faceFatigueUrl + cameraId, Map.of(
                "userId", cameraId,
                "status", status,
                "message", runtimeStatus.message,
                "timestamp", System.currentTimeMillis()
        ));
    }

    private boolean sleepBeforeRetry(CameraWorker worker) {
        try {
            Thread.sleep(RETRY_DELAY_MS);
            return worker.running.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    private boolean isRtspReachable(String rtspUrl) {
        try {
            URI uri = URI.create(rtspUrl);
            String host = uri.getHost();
            int port = uri.getPort() > 0 ? uri.getPort() : 554;
            if (host == null || host.isBlank()) {
                return false;
            }
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress(host, port), RTSP_PROBE_TIMEOUT_MS);
                return true;
            }
        } catch (Exception e) {
            return false;
        }
    }

    static String cameraSourceKey(CameraConfig camera) {
        return camera.isLocal()
                ? "local:" + (camera.getDeviceIndex() == null ? 0 : camera.getDeviceIndex())
                : "rtsp:" + camera.getRtspUrl();
    }

    private class CameraWorker implements Runnable {
        private final CameraConfig camera;
        private final String cameraId;
        private final String rtspUrl;
        private final String sourceKey;
        private final AtomicBoolean running = new AtomicBoolean(true);
        private final Thread thread;
        private boolean wasRtspReachable = false;

        private CameraWorker(CameraConfig camera) {
            this.camera = camera;
            this.cameraId = camera.getId();
            this.rtspUrl = camera.getRtspUrl();
            this.sourceKey = cameraSourceKey(camera);
            this.thread = new Thread(this, "RTSP-Stream-" + cameraId);
            this.thread.setDaemon(true);
        }

        private void start() {
            thread.start();
        }

        private void stop() {
            running.set(false);
            thread.interrupt();
        }

        private boolean isAlive() {
            return running.get() && thread.isAlive();
        }

        @Override
        public void run() {
            publishCameraStatus(cameraId, "reconnecting", "Camera stream worker started.");
            while (running.get() && !Thread.currentThread().isInterrupted()) {
                try {
                    if (!faceDetectService.isConnected()) {
                        publishCameraStatus(cameraId, "model_offline", "Face model service is offline.");
                        if (!sleepBeforeRetry(this)) {
                            break;
                        }
                        continue;
                    }

                    if (!camera.isLocal() && !isRtspReachable(rtspUrl)) {
                        wasRtspReachable = false;
                        publishCameraStatus(cameraId, "camera_unreachable", "RTSP port is not reachable yet.");
                        if (!sleepBeforeRetry(this)) {
                            break;
                        }
                        continue;
                    }

                    if (!camera.isLocal() && !wasRtspReachable) {
                        wasRtspReachable = true;
                        boolean refreshed = cameraConfigService.refreshRuntime(camera);
                        publishCameraStatus(
                                cameraId,
                                "stream_ready",
                                refreshed ? "RTSP is reachable and go2rtc runtime was refreshed." : "RTSP is reachable, but go2rtc runtime refresh failed."
                        );
                    }

                    publishCameraStatus(cameraId, "reconnecting", "Connecting camera stream.");
                    if (camera.isLocal()) {
                        boolean refreshed = cameraConfigService.refreshRuntime(camera);
                        if (!refreshed) {
                            log.debug("go2rtc local camera refresh did not return success | id={}", cameraId);
                        }
                        String modelInputUrl = cameraConfigService.modelInputUrl(camera);
                        log.info("Connecting local camera through go2rtc | id={} url={}", cameraId, modelInputUrl);
                        faceDetectService.processVideo(modelInputUrl, cameraId);
                    } else {
                        log.info("Connecting camera stream | id={} url={}", cameraId, rtspUrl);
                        faceDetectService.processVideo(rtspUrl, cameraId);
                    }
                    if (running.get()) {
                        publishCameraStatus(cameraId, "offline", "Camera stream disconnected.");
                    }
                } catch (Exception e) {
                    CameraRuntimeStatus status = streamStatuses.computeIfAbsent(cameraId, CameraRuntimeStatus::new);
                    status.retryCount.incrementAndGet();
                    String nextStatus = faceDetectService.isConnected() ? "offline" : "model_offline";
                    publishCameraStatus(cameraId, nextStatus, e.getMessage());
                    log.warn("Camera stream failed, retrying in {} ms | id={} message={}", RETRY_DELAY_MS, cameraId, e.getMessage(), e);
                }

                if (!sleepBeforeRetry(this)) {
                    break;
                }
            }
            faceDetectService.clearCamera(cameraId);
            publishCameraStatus(cameraId, "offline", "Camera stream worker stopped.");
            log.warn("Camera stream stopped | id={}", cameraId);
        }
    }

    private static class CameraRuntimeStatus {
        private final String cameraId;
        private final AtomicLong retryCount = new AtomicLong(0);
        private volatile String status = "idle";
        private volatile String message = "";
        private volatile long lastFrameAt = 0;
        private volatile long updatedAt = 0;

        private CameraRuntimeStatus(String cameraId) {
            this.cameraId = cameraId;
        }

        private Map<String, Object> toMap(boolean modelConnected, long lastSentFrameAt, Map<String, Object> metrics) {
            long effectiveLastFrameAt = Math.max(lastFrameAt, lastSentFrameAt);
            Map<String, Object> result = new java.util.HashMap<>(metrics);
            result.putAll(Map.of(
                    "cameraId", cameraId,
                    "status", status,
                    "message", message,
                    "lastFrameAt", effectiveLastFrameAt,
                    "retryCount", retryCount.get(),
                    "modelConnected", modelConnected,
                    "updatedAt", updatedAt
            ));
            return result;
        }
    }
}
