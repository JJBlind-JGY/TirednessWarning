package com.server.faceservice.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.CameraConfig;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Service
public class CameraConfigService {
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Path configPath;

    public CameraConfigService(
            @Value("${app.camera.config-file:camera-config.json}") String configFile
    ) {
        this.configPath = Path.of(configFile);
    }

    public synchronized List<CameraConfig> list() {
        if (!Files.exists(configPath)) {
            List<CameraConfig> initial = new ArrayList<>();
            save(initial);
            return initial;
        }

        try {
            List<CameraConfig> cameras = objectMapper.readValue(
                    configPath.toFile(),
                    new TypeReference<List<CameraConfig>>() {
                    }
            );
            return cameras == null ? new ArrayList<>() : cameras;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read camera config: " + configPath, e);
        }
    }

    public synchronized CameraConfig upsert(CameraConfig camera) {
        CameraConfig normalized = normalize(camera);
        List<CameraConfig> cameras = list();
        Optional<CameraConfig> existing = cameras.stream()
                .filter(item -> item.getId().equals(normalized.getId()))
                .findFirst();

        if (existing.isPresent()) {
            CameraConfig target = existing.get();
            target.setName(normalized.getName());
            target.setRtspUrl(normalized.getRtspUrl());
        } else {
            cameras.add(normalized);
        }

        save(cameras);
        return normalized;
    }

    public synchronized boolean remove(String cameraId) {
        List<CameraConfig> cameras = list();
        boolean removed = cameras.removeIf(item -> item.getId().equals(cameraId));
        if (removed) {
            save(cameras);
        }
        return removed;
    }

    private CameraConfig normalize(CameraConfig camera) {
        String id = StringUtils.hasText(camera.getId()) ? camera.getId().trim() : "camera_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String name = StringUtils.hasText(camera.getName()) ? camera.getName().trim() : id;
        String rtspUrl = StringUtils.hasText(camera.getRtspUrl()) ? camera.getRtspUrl().trim() : "";
        if (!StringUtils.hasText(rtspUrl)) {
            throw new IllegalArgumentException("RTSP url is required");
        }
        return new CameraConfig(id, name, rtspUrl);
    }

    private void save(List<CameraConfig> cameras) {
        try {
            Path parent = configPath.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(configPath.toFile(), cameras);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to write camera config: " + configPath, e);
        }
    }
}
