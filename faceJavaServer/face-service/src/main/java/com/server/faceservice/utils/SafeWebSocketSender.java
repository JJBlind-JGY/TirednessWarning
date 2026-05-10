package com.server.faceservice.utils;

import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

public class SafeWebSocketSender {
    private static final Logger LOGGER = LoggerFactory.getLogger(SafeWebSocketSender.class);
    private final BlockingQueue<String> readyCameras = new LinkedBlockingQueue<>();
    private final Map<String, CameraQueue> cameraQueues = new ConcurrentHashMap<>();
    private final Map<String, CameraSendMetrics> metrics = new ConcurrentHashMap<>();
    private final ModelWebsocket websocket;
    private volatile boolean running = true;

    public SafeWebSocketSender(ModelWebsocket websocket) {
        if (websocket == null) {
            LOGGER.error("FaceDetectService initialized with modelWebsocket: {}", websocket);
        }
        this.websocket = websocket;
        websocket.connect();
        startConsumer();
    }

    private void startConsumer() {
        Thread consumerThread = new Thread(() -> {
            while (running) {
                String cameraId = null;
                try {
                    cameraId = readyCameras.poll(100, TimeUnit.MILLISECONDS);
                    if (cameraId == null) {
                        continue;
                    }

                    CameraQueue queue = cameraQueues.get(cameraId);
                    if (queue == null) {
                        continue;
                    }

                    byte[] data = queue.latestFrame.getAndSet(null);
                    if (data != null && websocket.isOpen()) {
                        synchronized (websocket) {
                            websocket.send(data);
                        }
                        getMetrics(cameraId).lastSentAt.set(System.currentTimeMillis());
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } catch (Exception e) {
                    LOGGER.warn("failed to send frame to model websocket: {}", e.getMessage(), e);
                } finally {
                    if (cameraId != null) {
                        markDequeued(cameraId);
                    }
                }
            }
        });
        consumerThread.setDaemon(true);
        consumerThread.start();
    }

    public void sendAsync(String cameraId, byte[] data) {
        if (cameraId == null || cameraId.isBlank() || data == null) {
            return;
        }

        CameraQueue queue = cameraQueues.computeIfAbsent(cameraId, ignored -> new CameraQueue());
        CameraSendMetrics cameraMetrics = getMetrics(cameraId);
        if (queue.latestFrame.getAndSet(data) != null) {
            cameraMetrics.framesDropped.incrementAndGet();
        }
        cameraMetrics.framesSubmitted.incrementAndGet();
        enqueue(cameraId, queue);
    }

    public void clearCamera(String cameraId) {
        if (cameraId != null) {
            cameraQueues.remove(cameraId);
            metrics.remove(cameraId);
        }
    }

    public Map<String, Object> metricsSnapshot(String cameraId) {
        return getMetrics(cameraId).toMap();
    }

    private CameraSendMetrics getMetrics(String cameraId) {
        return metrics.computeIfAbsent(cameraId, ignored -> new CameraSendMetrics());
    }

    private void enqueue(String cameraId, CameraQueue queue) {
        if (queue.queued.compareAndSet(false, true)) {
            readyCameras.offer(cameraId);
        }
    }

    private void markDequeued(String cameraId) {
        CameraQueue queue = cameraQueues.get(cameraId);
        if (queue == null) {
            return;
        }
        queue.queued.set(false);
        if (queue.latestFrame.get() != null) {
            enqueue(cameraId, queue);
        }
    }

    @PreDestroy
    public void shutdown() {
        running = false;
        cameraQueues.clear();
        metrics.clear();
    }

    private static class CameraQueue {
        private final AtomicReference<byte[]> latestFrame = new AtomicReference<>();
        private final AtomicBoolean queued = new AtomicBoolean(false);
    }

    private static class CameraSendMetrics {
        private final AtomicLong framesSubmitted = new AtomicLong(0);
        private final AtomicLong framesDropped = new AtomicLong(0);
        private final AtomicLong lastSentAt = new AtomicLong(0);

        private Map<String, Object> toMap() {
            return Map.of(
                    "framesSubmitted", framesSubmitted.get(),
                    "framesDropped", framesDropped.get(),
                    "lastSentAt", lastSentAt.get()
            );
        }
    }
}
