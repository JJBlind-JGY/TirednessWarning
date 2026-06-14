package com.server.faceservice.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.AbnormalSampleRequest;
import org.bytedeco.ffmpeg.global.avcodec;
import org.bytedeco.javacv.FFmpegFrameRecorder;
import org.bytedeco.javacv.Frame;
import org.bytedeco.javacv.Java2DFrameConverter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

@Service
public class AbnormalSampleService {
    private static final Logger log = LoggerFactory.getLogger(AbnormalSampleService.class);
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient httpClient = HttpClient.newBuilder().build();
    private final Map<String, ArrayDeque<VideoFrameSample>> videoFrames = new ConcurrentHashMap<>();
    private final Map<String, ArrayDeque<JSONObject>> facePredictions = new ConcurrentHashMap<>();
    private final Path sampleRoot;
    private final Path normalSampleRoot;
    private final String eegSnapshotBaseUrl;
    private final ZoneId zoneId;
    private final long windowMs;
    private final long videoCacheMs;
    private final int videoFps;
    private final long maxBytes;
    private final long normalMaxBytes;

    public AbnormalSampleService(
            @Value("${app.abnormal-sample.dir:data/abnormal-samples}") String sampleDir,
            @Value("${app.normal-sample.dir:data/normal-samples}") String normalSampleDir,
            @Value("${app.abnormal-sample.eeg-base-url:http://127.0.0.1:5000}") String eegSnapshotBaseUrl,
            @Value("${app.abnormal-sample.zone-id:Asia/Shanghai}") String configuredZoneId,
            @Value("${app.abnormal-sample.window-ms:10000}") long windowMs,
            @Value("${app.abnormal-sample.video-cache-ms:15000}") long videoCacheMs,
            @Value("${app.abnormal-sample.video-export-fps:${app.abnormal-sample.video-fps:15}}") int videoFps,
            @Value("${app.abnormal-sample.max-bytes:53687091200}") long maxBytes,
            @Value("${app.normal-sample.max-bytes:21474836480}") long normalMaxBytes
    ) {
        this.sampleRoot = Path.of(sampleDir);
        this.normalSampleRoot = Path.of(normalSampleDir);
        this.eegSnapshotBaseUrl = trimTrailingSlash(eegSnapshotBaseUrl);
        this.zoneId = ZoneId.of(StringUtils.hasText(configuredZoneId) ? configuredZoneId : "Asia/Shanghai");
        this.windowMs = Math.max(1000, windowMs);
        this.videoCacheMs = Math.max(this.windowMs, videoCacheMs);
        this.videoFps = Math.max(1, videoFps);
        this.maxBytes = Math.max(0, maxBytes);
        this.normalMaxBytes = Math.max(0, normalMaxBytes);
    }

    public boolean shouldRecordVideoFrame(String cameraId, long timestamp) {
        if (!StringUtils.hasText(cameraId)) {
            return false;
        }
        ArrayDeque<VideoFrameSample> queue = videoFrames.computeIfAbsent(cameraId, ignored -> new ArrayDeque<>());
        synchronized (queue) {
            VideoFrameSample latest = queue.peekLast();
            return latest == null || timestamp - latest.timestamp >= 1000L / videoFps;
        }
    }

    public void recordVideoFrame(String cameraId, long timestamp, byte[] jpegBytes) {
        if (!StringUtils.hasText(cameraId) || jpegBytes == null || jpegBytes.length == 0) {
            return;
        }
        ArrayDeque<VideoFrameSample> queue = videoFrames.computeIfAbsent(cameraId, ignored -> new ArrayDeque<>());
        synchronized (queue) {
            VideoFrameSample latest = queue.peekLast();
            if (latest != null && timestamp - latest.timestamp < 1000L / videoFps) {
                return;
            }
            queue.addLast(new VideoFrameSample(timestamp, jpegBytes));
            trimVideoQueue(queue, timestamp - videoCacheMs);
        }
    }

    public void recordFacePrediction(JSONObject payload) {
        if (payload == null) {
            return;
        }
        String cameraId = payload.getString("userId");
        if (!StringUtils.hasText(cameraId)) {
            return;
        }
        JSONObject copy = new JSONObject(payload);
        copy.remove("image");
        copy.put("recordedAt", System.currentTimeMillis());
        ArrayDeque<JSONObject> queue = facePredictions.computeIfAbsent(cameraId, ignored -> new ArrayDeque<>());
        synchronized (queue) {
            queue.addLast(copy);
            trimFaceQueue(queue, System.currentTimeMillis() - videoCacheMs);
        }
    }

    public synchronized Map<String, Object> capture(AbnormalSampleRequest request) {
        long now = System.currentTimeMillis();
        long eventTs = request.getTimestamp() > 0 ? request.getTimestamp() : now;
        String eventId = StringUtils.hasText(request.getEventId()) ? sanitize(request.getEventId()) : "sample_" + UUID.randomUUID().toString().replace("-", "");
        boolean normalSample = isNormalSample(request);
        Path targetRoot = normalSample ? normalSampleRoot : sampleRoot;
        long targetMaxBytes = normalSample ? normalMaxBytes : maxBytes;
        if (targetMaxBytes > 0 && directorySize(targetRoot) >= targetMaxBytes) {
            return Map.of("captureStatus", "skipped", "reason", "sample storage limit reached", "eventId", eventId);
        }

        long fromTs = Math.max(0, eventTs - windowMs);
        LocalDate date = Instant.ofEpochMilli(eventTs).atZone(zoneId).toLocalDate();
        Path workDir = targetRoot
                .resolve(String.format("%04d", date.getYear()))
                .resolve(String.format("%02d", date.getMonthValue()))
                .resolve(String.format("%02d", date.getDayOfMonth()))
                .resolve(eventId);
        Path zipPath = workDir.getParent().resolve(eventId + ".zip");

        try {
            List<VideoFrameSample> frames = getVideoFrames(request.getCameraId(), fromTs, eventTs);
            List<JSONObject> faceLogs = getFacePredictions(request.getCameraId(), fromTs, eventTs);
            JSONObject eegSnapshot = fetchEegSnapshot(request.getWorkerId(), eventTs);
            if (requiresCompleteSensorData(request) && (faceLogs.isEmpty() || !hasEegSnapshot(eegSnapshot))) {
                return Map.of(
                        "captureStatus", "skipped",
                        "reason", "sample requires face and eeg data",
                        "eventId", eventId,
                        "missing", missingNormalRequirements(faceLogs, eegSnapshot)
                );
            }

            Files.createDirectories(workDir);
            boolean videoOk = writeVideo(workDir.resolve("video").resolve("face.mp4"), frames);
            writeJsonLines(workDir.resolve("face").resolve("predictions.jsonl"), faceLogs);
            writeEegFiles(workDir.resolve("eeg"), eegSnapshot);

            List<String> missing = new ArrayList<>();
            boolean videoComplete = isVideoComplete(frames, fromTs, eventTs);
            boolean eegRawComplete = isEegRawComplete(eegSnapshot);
            if (!videoOk) missing.add("video");
            else if (!videoComplete) missing.add("video_incomplete");
            if (faceLogs.isEmpty()) missing.add("face_predictions");
            if (eegSnapshot == null) missing.add("eeg_snapshot");
            else if (!eegRawComplete) missing.add("eeg_raw_incomplete");

            Map<String, Object> manifest = buildManifest(request, eventId, eventTs, fromTs, !missing.isEmpty(), missing, frames, faceLogs.size(), eegSnapshot);
            Files.writeString(workDir.resolve("manifest.json"), objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(manifest), StandardCharsets.UTF_8);
            zipDirectory(workDir, zipPath);
            return Map.of("captureStatus", "ok", "samplePath", zipPath.toString(), "eventId", eventId, "partial", !missing.isEmpty(), "missing", missing);
        } catch (Exception e) {
            log.warn("{} sample capture failed | eventId={} message={}", normalSample ? "normal" : "abnormal", eventId, e.getMessage(), e);
            return Map.of("captureStatus", "failed", "reason", e.getMessage(), "eventId", eventId);
        }
    }

    private boolean isNormalSample(AbnormalSampleRequest request) {
        return "normal_sample".equals(defaultString(request.getAlertType(), ""));
    }

    private boolean requiresCompleteSensorData(AbnormalSampleRequest request) {
        String alertType = defaultString(request.getAlertType(), "");
        return "normal_sample".equals(alertType) || "fusion_abnormal".equals(alertType);
    }

    private boolean hasEegSnapshot(JSONObject eegSnapshot) {
        if (eegSnapshot == null) {
            return false;
        }
        return eegSnapshot.getIntValue("predictionCount") > 0
                || eegSnapshot.getIntValue("rawTgamCount") > 0
                || eegSnapshot.getIntValue("rawWaveCount") > 0;
    }

    private List<String> missingNormalRequirements(List<JSONObject> faceLogs, JSONObject eegSnapshot) {
        List<String> missing = new ArrayList<>();
        if (faceLogs == null || faceLogs.isEmpty()) {
            missing.add("face_predictions");
        }
        if (!hasEegSnapshot(eegSnapshot)) {
            missing.add("eeg_snapshot");
        }
        return missing;
    }

    private Map<String, Object> buildManifest(AbnormalSampleRequest request, String eventId, long eventTs, long fromTs,
                                              boolean partial, List<String> missing, List<VideoFrameSample> videoFrames,
                                              int facePredictionCount, JSONObject eegSnapshot) {
        Map<String, Object> manifest = new HashMap<>();
        long videoStart = videoFrames.isEmpty() ? 0 : videoFrames.get(0).timestamp;
        long videoEnd = videoFrames.isEmpty() ? 0 : videoFrames.get(videoFrames.size() - 1).timestamp;
        long videoCoverageMs = videoFrames.size() <= 1 ? 0 : videoEnd - videoStart;
        manifest.put("version", 1);
        manifest.put("eventId", eventId);
        manifest.put("timestamp", eventTs);
        manifest.put("windowStart", fromTs);
        manifest.put("windowEnd", eventTs);
        manifest.put("windowMs", windowMs);
        manifest.put("personId", defaultString(request.getPersonId(), ""));
        manifest.put("personName", defaultString(request.getPersonName(), "未绑定人员"));
        manifest.put("workerId", request.getWorkerId());
        manifest.put("cameraId", defaultString(request.getCameraId(), ""));
        manifest.put("alertType", defaultString(request.getAlertType(), "face_abnormal"));
        manifest.put("sampleType", isNormalSample(request) ? "normal" : "abnormal");
        manifest.put("emotion", defaultString(request.getEmotion(), ""));
        manifest.put("message", defaultString(request.getMessage(), ""));
        manifest.put("partial", partial);
        manifest.put("missing", missing);
        manifest.put("videoExportFps", videoFps);
        manifest.put("videoExpectedFrameCount", expectedVideoFrameCount());
        manifest.put("videoFrameCount", videoFrames.size());
        manifest.put("videoStart", videoStart);
        manifest.put("videoEnd", videoEnd);
        manifest.put("videoCoverageMs", videoCoverageMs);
        manifest.put("videoComplete", isVideoComplete(videoFrames, fromTs, eventTs));
        manifest.put("facePredictionCount", facePredictionCount);
        manifest.put("eegPayloadCount", eegSnapshot == null ? 0 : eegSnapshot.getIntValue("predictionCount"));
        manifest.put("eegRawFs", eegSnapshot == null ? 0 : eegSnapshot.getIntValue("rawTgamFs"));
        manifest.put("eegRawCount", eegSnapshot == null ? 0 : eegSnapshot.getIntValue("rawTgamCount"));
        manifest.put("eegRawWindowStart", eegSnapshot == null ? 0 : eegSnapshot.getLongValue("rawTgamWindowStart"));
        manifest.put("eegRawWindowEnd", eegSnapshot == null ? 0 : eegSnapshot.getLongValue("rawTgamWindowEnd"));
        manifest.put("eegRawComplete", isEegRawComplete(eegSnapshot));
        return manifest;
    }

    private JSONObject fetchEegSnapshot(Integer workerId, long before) {
        if (workerId == null || !StringUtils.hasText(eegSnapshotBaseUrl)) {
            return null;
        }
        try {
            String query = "/eeg/snapshot?workerId=" + workerId + "&seconds=" + Math.max(1, windowMs / 1000) + "&before=" + before;
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(eegSnapshotBaseUrl + query))
                    .timeout(java.time.Duration.ofSeconds(3))
                    .GET()
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return null;
            }
            return JSON.parseObject(response.body());
        } catch (Exception e) {
            log.debug("eeg snapshot fetch failed: {}", e.getMessage());
            return null;
        }
    }

    private void writeEegFiles(Path eegDir, JSONObject snapshot) throws IOException {
        Files.createDirectories(eegDir);
        if (snapshot == null) {
            Files.writeString(eegDir.resolve("raw_wave.json"), "{\"samples\":[],\"partial\":true}", StandardCharsets.UTF_8);
            Files.writeString(eegDir.resolve("raw_tgam.json"), "{\"samples\":[],\"partial\":true}", StandardCharsets.UTF_8);
            Files.writeString(eegDir.resolve("predictions.jsonl"), "", StandardCharsets.UTF_8);
            return;
        }
        JSONObject rawWave = new JSONObject();
        rawWave.put("workerId", snapshot.get("workerId"));
        rawWave.put("waveFs", snapshot.get("waveFs"));
        rawWave.put("windowStart", snapshot.get("windowStart"));
        rawWave.put("windowEnd", snapshot.get("windowEnd"));
        rawWave.put("samples", snapshot.getJSONArray("rawWave"));
        Files.writeString(eegDir.resolve("raw_wave.json"), rawWave.toJSONString(), StandardCharsets.UTF_8);
        JSONObject rawTgam = new JSONObject();
        rawTgam.put("workerId", snapshot.get("workerId"));
        rawTgam.put("rawTgamFs", snapshot.get("rawTgamFs"));
        rawTgam.put("windowStart", snapshot.get("rawTgamWindowStart"));
        rawTgam.put("windowEnd", snapshot.get("rawTgamWindowEnd"));
        rawTgam.put("targetWindowStart", snapshot.get("windowStart"));
        rawTgam.put("targetWindowEnd", snapshot.get("windowEnd"));
        rawTgam.put("sampleCount", snapshot.getIntValue("rawTgamCount"));
        rawTgam.put("partial", !isEegRawComplete(snapshot));
        rawTgam.put("samples", snapshot.getJSONArray("rawTgamSamples"));
        Files.writeString(eegDir.resolve("raw_tgam.json"), rawTgam.toJSONString(), StandardCharsets.UTF_8);
        JSONArray predictions = snapshot.getJSONArray("predictions");
        List<String> lines = new ArrayList<>();
        if (predictions != null) {
            for (Object prediction : predictions) {
                lines.add(JSON.toJSONString(prediction));
            }
        }
        Files.write(eegDir.resolve("predictions.jsonl"), lines, StandardCharsets.UTF_8);
    }

    private boolean writeVideo(Path path, List<VideoFrameSample> frames) throws Exception {
        if (frames.isEmpty()) {
            return false;
        }
        Files.createDirectories(path.getParent());
        Java2DFrameConverter converter = new Java2DFrameConverter();
        BufferedImage first = ImageIO.read(new ByteArrayInputStream(frames.get(0).jpegBytes));
        if (first == null) {
            return false;
        }
        double effectiveFps = Math.max(1.0, frames.size() / Math.max(1.0, windowMs / 1000.0));
        try (FFmpegFrameRecorder recorder = new FFmpegFrameRecorder(path.toFile(), first.getWidth(), first.getHeight())) {
            recorder.setFormat("mp4");
            recorder.setVideoCodec(avcodec.AV_CODEC_ID_H264);
            recorder.setPixelFormat(org.bytedeco.ffmpeg.global.avutil.AV_PIX_FMT_YUV420P);
            recorder.setVideoOption("colorspace", "bt709");
            recorder.setVideoOption("color_primaries", "bt709");
            recorder.setVideoOption("color_trc", "bt709");
            recorder.setVideoOption("color_range", "tv");
            recorder.setFrameRate(effectiveFps);
            recorder.setVideoBitrate(700_000);
            recorder.start();
            for (VideoFrameSample sample : frames) {
                BufferedImage image = ImageIO.read(new ByteArrayInputStream(sample.jpegBytes));
                if (image == null) continue;
                Frame frame = converter.convert(image);
                recorder.record(frame);
            }
        }
        return true;
    }

    private boolean isVideoComplete(List<VideoFrameSample> frames, long fromTs, long toTs) {
        if (frames.isEmpty()) {
            return false;
        }
        long first = frames.get(0).timestamp;
        long last = frames.get(frames.size() - 1).timestamp;
        long expectedCoverageMs = Math.max(1000, toTs - fromTs);
        long actualCoverageMs = Math.max(0, last - first);
        return frames.size() >= Math.max(1, Math.floor(expectedVideoFrameCount() * 0.8))
                && actualCoverageMs >= expectedCoverageMs * 0.85
                && first <= fromTs + 1000
                && last >= toTs - 1000;
    }

    private int expectedVideoFrameCount() {
        return (int) Math.ceil((windowMs / 1000.0) * videoFps);
    }

    private boolean isEegRawComplete(JSONObject snapshot) {
        if (snapshot == null) {
            return false;
        }
        int rawFs = snapshot.getIntValue("rawTgamFs");
        int rawCount = snapshot.getIntValue("rawTgamCount");
        if (rawFs <= 0) {
            return false;
        }
        int expected = (int) Math.floor((windowMs / 1000.0) * rawFs);
        return rawCount >= Math.max(1, Math.floor(expected * 0.8));
    }

    private void writeJsonLines(Path path, List<JSONObject> logs) throws IOException {
        Files.createDirectories(path.getParent());
        List<String> lines = logs.stream().map(item -> item.toJSONString()).toList();
        Files.write(path, lines, StandardCharsets.UTF_8);
    }

    private List<VideoFrameSample> getVideoFrames(String cameraId, long fromTs, long toTs) {
        ArrayDeque<VideoFrameSample> queue = videoFrames.get(cameraId);
        if (queue == null) return List.of();
        synchronized (queue) {
            return queue.stream().filter(item -> item.timestamp >= fromTs && item.timestamp <= toTs).toList();
        }
    }

    private List<JSONObject> getFacePredictions(String cameraId, long fromTs, long toTs) {
        ArrayDeque<JSONObject> queue = facePredictions.get(cameraId);
        if (queue == null) return List.of();
        synchronized (queue) {
            return queue.stream()
                    .filter(item -> {
                        long ts = item.getLongValue("timestamp");
                        if (ts <= 0) ts = item.getLongValue("recordedAt");
                        return ts >= fromTs && ts <= toTs;
                    })
                    .toList();
        }
    }

    private void trimVideoQueue(ArrayDeque<VideoFrameSample> queue, long cutoff) {
        while (!queue.isEmpty() && queue.peekFirst().timestamp < cutoff) queue.removeFirst();
    }

    private void trimFaceQueue(ArrayDeque<JSONObject> queue, long cutoff) {
        while (!queue.isEmpty()) {
            JSONObject first = queue.peekFirst();
            long ts = first.getLongValue("timestamp");
            if (ts <= 0) ts = first.getLongValue("recordedAt");
            if (ts >= cutoff) return;
            queue.removeFirst();
        }
    }

    private void zipDirectory(Path sourceDir, Path zipPath) throws IOException {
        Files.createDirectories(zipPath.getParent());
        try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(zipPath))) {
            Files.walk(sourceDir)
                    .filter(Files::isRegularFile)
                    .sorted(Comparator.comparing(Path::toString))
                    .forEach(path -> {
                        try {
                            ZipEntry entry = new ZipEntry(sourceDir.relativize(path).toString().replace("\\", "/"));
                            zip.putNextEntry(entry);
                            Files.copy(path, zip);
                            zip.closeEntry();
                        } catch (IOException e) {
                            throw new IllegalStateException(e);
                        }
                    });
        }
    }

    private long directorySize(Path path) {
        if (!Files.exists(path)) return 0;
        try {
            return Files.walk(path).filter(Files::isRegularFile).mapToLong(item -> {
                try { return Files.size(item); } catch (IOException e) { return 0; }
            }).sum();
        } catch (IOException e) {
            return 0;
        }
    }

    private String defaultString(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private String sanitize(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("%", "_");
    }

    private String trimTrailingSlash(String value) {
        if (!StringUtils.hasText(value)) return "";
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) trimmed = trimmed.substring(0, trimmed.length() - 1);
        return trimmed;
    }

    private record VideoFrameSample(long timestamp, byte[] jpegBytes) {
    }
}
