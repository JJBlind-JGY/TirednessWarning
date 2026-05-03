package com.server.faceservice.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.CameraConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Service
public class CameraConfigService {
    private static final Logger log = LoggerFactory.getLogger(CameraConfigService.class);

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2))
            .build();
    private final Path configPath;
    private final Path go2rtcConfigPath;
    private final String go2rtcApiBase;

    public CameraConfigService(
            @Value("${app.camera.config-file:camera-config.json}") String configFile,
            @Value("${app.go2rtc.config-file:go2rtc/go2rtc.yaml}") String go2rtcConfigFile,
            @Value("${app.go2rtc.api-base:http://127.0.0.1:1984}") String go2rtcApiBase
    ) {
        this.configPath = Path.of(configFile);
        this.go2rtcConfigPath = resolveGo2RtcConfigPath(go2rtcConfigFile);
        this.go2rtcApiBase = trimTrailingSlash(go2rtcApiBase);
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
            List<CameraConfig> normalized = cameras == null ? new ArrayList<>() : cameras;
            saveGo2RtcConfig(normalized);
            return normalized;
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
            target.setStreamName(normalized.getStreamName());
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
        String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName().trim() : id;
        if (!StringUtils.hasText(rtspUrl)) {
            throw new IllegalArgumentException("RTSP url is required");
        }
        return new CameraConfig(id, name, rtspUrl, streamName);
    }

    private void save(List<CameraConfig> cameras) {
        try {
            Path parent = configPath.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(configPath.toFile(), cameras);
            saveGo2RtcConfig(cameras);
            syncGo2RtcRuntime(cameras);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to write camera config: " + configPath, e);
        }
    }

    private void saveGo2RtcConfig(List<CameraConfig> cameras) throws IOException {
        Path parent = go2rtcConfigPath.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        StringBuilder yaml = new StringBuilder();
        yaml.append("streams:\n");
        for (CameraConfig camera : cameras) {
            if (!StringUtils.hasText(camera.getRtspUrl())) {
                continue;
            }
            String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId();
            yaml.append("  ").append(streamName).append(":\n");
            yaml.append("    - ").append(camera.getRtspUrl()).append("\n");
        }
        yaml.append("\nwebrtc:\n");
        yaml.append("  listen: :1984\n\n");
        yaml.append("api:\n");
        yaml.append("  listen: :1984\n");
        Files.writeString(go2rtcConfigPath, yaml.toString());
    }

    private void syncGo2RtcRuntime(List<CameraConfig> cameras) {
        if (!StringUtils.hasText(go2rtcApiBase)) {
            return;
        }

        boolean reloaded = tryGo2RtcRequest("POST", "/api/reload")
                || tryGo2RtcRequest("GET", "/api/reload")
                || syncStreamsViaApi(cameras);

        if (reloaded) {
            log.info("go2rtc runtime sync completed after camera config update.");
        } else {
            log.warn("go2rtc config was written to {}, but runtime reload failed. If the new camera does not appear, restart go2rtc with start-all.ps1.",
                    go2rtcConfigPath.toAbsolutePath());
        }
    }

    private boolean syncStreamsViaApi(List<CameraConfig> cameras) {
        boolean changed = false;
        for (CameraConfig camera : cameras) {
            if (!StringUtils.hasText(camera.getRtspUrl())) {
                continue;
            }
            String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId();
            String query = "?dst=" + urlEncode(streamName) + "&src=" + urlEncode(camera.getRtspUrl());
            changed = tryGo2RtcRequest("POST", "/api/streams" + query) || changed;
        }
        return changed;
    }

    private boolean tryGo2RtcRequest(String method, String pathAndQuery) {
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(go2rtcApiBase + pathAndQuery))
                    .timeout(Duration.ofSeconds(2));
            HttpRequest request = "POST".equalsIgnoreCase(method)
                    ? builder.POST(HttpRequest.BodyPublishers.noBody()).build()
                    : builder.GET().build();
            HttpResponse<Void> response = httpClient.send(request, HttpResponse.BodyHandlers.discarding());
            return response.statusCode() >= 200 && response.statusCode() < 300;
        } catch (Exception e) {
            log.debug("go2rtc {} {} failed: {}", method, pathAndQuery, e.getMessage());
            return false;
        }
    }

    private String urlEncode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
    }

    private String trimTrailingSlash(String value) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return trimmed;
    }

    private Path resolveGo2RtcConfigPath(String configuredPath) {
        Path configured = Path.of(configuredPath);
        if (configured.isAbsolute()) {
            return configured;
        }

        Path current = Path.of("").toAbsolutePath();
        while (current != null) {
            Path candidateRoot = current.resolve("go2rtc").resolve("go2rtc.exe");
            if (Files.exists(candidateRoot)) {
                return current.resolve(configuredPath);
            }
            current = current.getParent();
        }

        return configured;
    }
}
