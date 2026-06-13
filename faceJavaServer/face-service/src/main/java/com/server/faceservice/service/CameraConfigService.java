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
            List<CameraConfig> initial = loadGo2RtcStreams();
            save(initial);
            return initial;
        }

        try {
            List<CameraConfig> cameras = objectMapper.readValue(
                    configPath.toFile(),
                    new TypeReference<List<CameraConfig>>() {
                    }
            );
            List<CameraConfig> normalized = cameras == null
                    ? new ArrayList<>()
                    : new ArrayList<>(cameras.stream().map(this::normalize).toList());
            if (normalized.isEmpty()) {
                List<CameraConfig> imported = loadGo2RtcStreams();
                if (!imported.isEmpty()) {
                    save(imported);
                    return imported;
                }
            }
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

    public synchronized boolean refreshRuntime(CameraConfig camera) {
        if (camera == null) {
            return false;
        }
        boolean streamUpdated = syncStreamsViaApi(List.of(camera));
        boolean reloaded = tryGo2RtcRequest("POST", "/api/reload") || tryGo2RtcRequest("GET", "/api/reload");
        boolean refreshed = streamUpdated || reloaded;
        if (refreshed) {
            log.info("go2rtc runtime refreshed for stream: {}", StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId());
        } else {
            log.warn("go2rtc runtime refresh failed for stream: {}. Restart go2rtc if the browser stream remains stale.",
                    StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId());
        }
        return refreshed;
    }

    CameraConfig normalize(CameraConfig camera) {
        String id = StringUtils.hasText(camera.getId()) ? camera.getId().trim() : "camera_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String name = StringUtils.hasText(camera.getName()) ? camera.getName().trim() : id;
        String sourceType = StringUtils.hasText(camera.getSourceType()) ? camera.getSourceType().trim().toLowerCase() : "rtsp";
        if (!"rtsp".equals(sourceType) && !"local".equals(sourceType)) {
            throw new IllegalArgumentException("Camera sourceType must be rtsp or local");
        }
        int deviceIndex = camera.getDeviceIndex() == null ? 0 : camera.getDeviceIndex();
        if (deviceIndex < 0) {
            throw new IllegalArgumentException("Local camera deviceIndex must be zero or greater");
        }
        String rtspUrl = StringUtils.hasText(camera.getRtspUrl()) ? camera.getRtspUrl().trim() : "";
        String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName().trim() : id;
        if ("rtsp".equals(sourceType) && !StringUtils.hasText(rtspUrl)) {
            throw new IllegalArgumentException("RTSP url is required");
        }
        return new CameraConfig(id, name, sourceType, deviceIndex, rtspUrl, streamName);
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
        if ((cameras == null || cameras.isEmpty()) && Files.exists(go2rtcConfigPath)) {
            log.warn("Skip writing empty go2rtc stream config to preserve existing streams: {}", go2rtcConfigPath.toAbsolutePath());
            return;
        }

        Path parent = go2rtcConfigPath.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        StringBuilder yaml = new StringBuilder();
        yaml.append("streams:\n");
        for (CameraConfig camera : cameras) {
            String source = streamSource(camera);
            if (!StringUtils.hasText(source)) {
                continue;
            }
            String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId();
            yaml.append("  ").append(streamName).append(":\n");
            yaml.append("    - ").append(source).append("\n");
        }
        yaml.append("\nwebrtc:\n");
        yaml.append("  listen: :1984\n\n");
        yaml.append("rtsp:\n");
        yaml.append("  listen: :8554\n\n");
        yaml.append("api:\n");
        yaml.append("  listen: :1984\n");
        Files.writeString(go2rtcConfigPath, yaml.toString());
    }

    private List<CameraConfig> loadGo2RtcStreams() {
        List<CameraConfig> cameras = new ArrayList<>();
        if (!Files.exists(go2rtcConfigPath)) {
            return cameras;
        }

        try {
            List<String> lines = Files.readAllLines(go2rtcConfigPath, StandardCharsets.UTF_8);
            boolean inStreams = false;
            String streamName = null;
            for (String line : lines) {
                String trimmed = line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                    continue;
                }
                if (!line.startsWith(" ") && trimmed.endsWith(":")) {
                    inStreams = "streams:".equals(trimmed);
                    streamName = null;
                    continue;
                }
                if (!inStreams) {
                    continue;
                }
                if (line.startsWith("  ") && !line.startsWith("    ") && trimmed.endsWith(":")) {
                    streamName = trimmed.substring(0, trimmed.length() - 1).trim();
                    continue;
                }
                if (streamName != null && line.startsWith("    - ")) {
                    String rtspUrl = trimmed.substring(2).trim();
                    if (StringUtils.hasText(rtspUrl)) {
                        cameras.add(new CameraConfig(streamName, streamName, rtspUrl, streamName));
                    }
                    streamName = null;
                }
            }
        } catch (IOException e) {
            log.warn("Failed to import streams from go2rtc config: {}", go2rtcConfigPath.toAbsolutePath(), e);
        }
        return cameras;
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
            String source = streamSource(camera);
            if (!StringUtils.hasText(source)) {
                continue;
            }
            String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId();
            String query = "?dst=" + urlEncode(streamName) + "&src=" + urlEncode(source);
            changed = tryGo2RtcRequest("POST", "/api/streams" + query) || changed;
        }
        return changed;
    }

    static String streamSource(CameraConfig camera) {
        if (camera == null) {
            return "";
        }
        if (camera.isLocal()) {
            int deviceIndex = camera.getDeviceIndex() == null ? 0 : camera.getDeviceIndex();
            return "ffmpeg:device?video=" + deviceIndex
                    + "&video_size=1280x720&framerate=30#video=h264";
        }
        return StringUtils.hasText(camera.getRtspUrl()) ? camera.getRtspUrl().trim() : "";
    }

    public String modelInputUrl(CameraConfig camera) {
        if (camera == null || !camera.isLocal()) {
            return camera == null ? "" : camera.getRtspUrl();
        }
        String streamName = StringUtils.hasText(camera.getStreamName()) ? camera.getStreamName() : camera.getId();
        return "rtsp://127.0.0.1:8554/" + streamName + "?video=h264";
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
