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

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class VideoStreamAutoRunner {

    private static final Logger log = LoggerFactory.getLogger(VideoStreamAutoRunner.class);

    @Autowired
    private FaceDetectService faceDetectService;

    @Autowired
    private CameraConfigService cameraConfigService;

    @Autowired
    private SimpMessagingTemplate messagingTemplate;

    @Value("${websocket.webUser.url:/topic/face_fatigue/}")
    private String faceFatigueUrl;

    private final Map<String, Thread> streamThreads = new ConcurrentHashMap<>();
    private final Map<String, String> streamUrls = new ConcurrentHashMap<>();
    private final Map<String, String> streamStatuses = new ConcurrentHashMap<>();

    @EventListener(ApplicationReadyEvent.class)
    public void startVideoStreamTask() {
        log.info("Application ready, loading camera streams...");
        reloadStreams();
    }

    public synchronized void reloadStreams() {
        Set<String> activeIds = new HashSet<>();
        cameraConfigService.list().stream()
                .filter(camera -> camera.getRtspUrl() != null && !camera.getRtspUrl().isBlank())
                .forEach(camera -> {
                    activeIds.add(camera.getId());
                    if (!camera.getRtspUrl().equals(streamUrls.get(camera.getId()))) {
                        stopCamera(camera.getId());
                    }
                    startCamera(camera.getId(), camera.getRtspUrl());
                });

        streamThreads.keySet().stream()
                .filter(cameraId -> !activeIds.contains(cameraId))
                .toList()
                .forEach(this::stopCamera);
    }

    public synchronized void startCamera(String cameraId, String rtspUrl) {
        Thread existing = streamThreads.get(cameraId);
        if (existing != null && existing.isAlive()) {
            return;
        }
        streamUrls.put(cameraId, rtspUrl);

        Thread streamThread = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    if (!faceDetectService.isConnected()) {
                        publishCameraStatus(cameraId, "model_offline", "面部模型服务未连接");
                        Thread.sleep(5000);
                        continue;
                    }
                    publishCameraStatus(cameraId, "reconnecting", "摄像头自动连接中");
                    log.info("Connecting camera stream | id={} url={}", cameraId, rtspUrl);
                    faceDetectService.processVideo(rtspUrl, cameraId);
                    publishCameraStatus(cameraId, "offline", "摄像头视频流已断开");
                } catch (Exception e) {
                    String status = faceDetectService.isConnected() ? "offline" : "model_offline";
                    publishCameraStatus(cameraId, status, e.getMessage());
                    log.error("Camera stream failed, retrying in 5 seconds | id={}", cameraId, e);
                    try {
                        Thread.sleep(5000);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            }
            publishCameraStatus(cameraId, "offline", "摄像头线程已停止");
            log.warn("Camera stream stopped | id={}", cameraId);
        });

        streamThread.setName("RTSP-Stream-" + cameraId);
        streamThread.setDaemon(true);
        streamThreads.put(cameraId, streamThread);
        streamThread.start();
    }

    public synchronized void stopCamera(String cameraId) {
        Thread thread = streamThreads.remove(cameraId);
        streamUrls.remove(cameraId);
        streamStatuses.remove(cameraId);
        if (thread != null) {
            thread.interrupt();
        }
        publishCameraStatus(cameraId, "offline", "摄像头已移除");
    }

    private void publishCameraStatus(String cameraId, String status, String message) {
        String previous = streamStatuses.put(cameraId, status);
        if (status.equals(previous) && !"online".equals(status)) {
            return;
        }
        messagingTemplate.convertAndSend(faceFatigueUrl + cameraId, Map.of(
                "userId", cameraId,
                "status", status,
                "message", message == null ? "" : message,
                "timestamp", System.currentTimeMillis()
        ));
    }
}
