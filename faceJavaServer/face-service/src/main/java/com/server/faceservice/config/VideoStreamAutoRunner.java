package com.server.faceservice.config;

import com.server.faceservice.service.CameraConfigService;
import com.server.faceservice.service.FaceDetectService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
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

    private final Map<String, Thread> streamThreads = new ConcurrentHashMap<>();
    private final Map<String, String> streamUrls = new ConcurrentHashMap<>();

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
                    log.info("Connecting camera stream | id={} url={}", cameraId, rtspUrl);
                    faceDetectService.processVideo(rtspUrl, cameraId);
                } catch (Exception e) {
                    log.error("Camera stream failed, retrying in 5 seconds | id={}", cameraId, e);
                    try {
                        Thread.sleep(5000);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            }
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
        if (thread != null) {
            thread.interrupt();
        }
    }
}
