package com.server.faceservice.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
public class DemoSampleService {
    private static final List<String> REQUIRED_FILES = List.of(
            "manifest.json",
            "video/face.mp4",
            "eeg/raw_wave.json",
            "eeg/raw_tgam.json",
            "eeg/predictions.jsonl",
            "face/predictions.jsonl"
    );
    private static final Set<String> ALLOWED_SUFFIXES = Set.of(".json", ".jsonl", ".mp4");

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Path sampleRoot;

    public DemoSampleService(@Value("${app.demo-sample.dir:data/demo-samples}") String sampleDir) {
        this.sampleRoot = Path.of(sampleDir);
    }

    public synchronized Map<String, Object> upload(MultipartFile[] files) {
        if (files == null || files.length == 0) {
            throw new IllegalArgumentException("请选择样本文件夹后再上传");
        }

        Map<String, MultipartFile> normalizedFiles = normalizeFiles(files);
        List<String> missing = REQUIRED_FILES.stream()
                .filter(required -> !normalizedFiles.containsKey(required))
                .toList();
        if (!missing.isEmpty()) {
            throw new DemoSampleValidationException("样本目录缺少必需文件", missing);
        }
        List<String> unexpected = normalizedFiles.keySet().stream()
                .filter(path -> !REQUIRED_FILES.contains(path))
                .toList();
        if (!unexpected.isEmpty()) {
            throw new DemoSampleValidationException("样本目录文件结构与系统保存结构不一致", unexpected);
        }

        MultipartFile video = normalizedFiles.get("video/face.mp4");
        String videoName = defaultString(video.getOriginalFilename(), "face.mp4").toLowerCase();
        if (!videoName.endsWith(".mp4")) {
            throw new DemoSampleValidationException("视频文件必须是 mp4 格式", List.of("video/face.mp4"));
        }
        validatePayloads(normalizedFiles);

        String sampleId = "demo-" + Instant.now().toEpochMilli() + "-" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        Path sampleDir = sampleRoot.resolve(sampleId).normalize();
        if (!sampleDir.startsWith(sampleRoot.normalize())) {
            throw new IllegalArgumentException("样本保存路径非法");
        }

        try {
            Files.createDirectories(sampleDir);
            for (Map.Entry<String, MultipartFile> entry : normalizedFiles.entrySet()) {
                String relativePath = entry.getKey();
                if (!isAllowedFile(relativePath)) {
                    continue;
                }
                Path target = sampleDir.resolve(relativePath).normalize();
                if (!target.startsWith(sampleDir)) {
                    throw new IllegalArgumentException("样本文件路径非法: " + relativePath);
                }
                Path parent = target.getParent();
                if (parent != null) {
                    Files.createDirectories(parent);
                }
                try (InputStream inputStream = entry.getValue().getInputStream()) {
                    Files.copy(inputStream, target);
                }
            }
            Map<String, Object> detail = load(sampleId);
            return Map.of("sampleId", sampleId, "sample", detail);
        } catch (IOException e) {
            throw new IllegalStateException("样本上传保存失败: " + e.getMessage(), e);
        }
    }

    public Map<String, Object> load(String sampleId) {
        Path sampleDir = resolveSampleDir(sampleId);
        if (!Files.isDirectory(sampleDir)) {
            throw new IllegalArgumentException("样本不存在");
        }

        try {
            JsonNode manifest = objectMapper.readTree(sampleDir.resolve("manifest.json").toFile());
            JsonNode rawWave = objectMapper.readTree(sampleDir.resolve("eeg/raw_wave.json").toFile());
            JsonNode rawTgam = objectMapper.readTree(sampleDir.resolve("eeg/raw_tgam.json").toFile());
            List<JsonNode> eegPredictions = readJsonLines(sampleDir.resolve("eeg/predictions.jsonl"));
            JsonNode latestEeg = eegPredictions.isEmpty() ? null : eegPredictions.get(eegPredictions.size() - 1);
            JsonNode latestFace = readLastJsonLine(sampleDir.resolve("face/predictions.jsonl"));

            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("sampleId", sampleId);
            detail.put("videoUrl", "/face-api/faceDetectService/demo-samples/" + sampleId + "/video");
            detail.put("manifest", objectMapper.convertValue(manifest, Map.class));
            detail.put("rawWave", buildRawWave(rawWave));
            detail.put("rawTgam", buildRawTgam(rawTgam));
            detail.put("latestEeg", latestEeg == null ? Map.of() : objectMapper.convertValue(latestEeg, Map.class));
            detail.put("eegTimeline", buildEegTimeline(eegPredictions));
            detail.put("latestFace", latestFace == null ? Map.of() : objectMapper.convertValue(latestFace, Map.class));
            return detail;
        } catch (IOException e) {
            throw new IllegalStateException("样本读取失败: " + e.getMessage(), e);
        }
    }

    public Resource video(String sampleId) {
        Path videoPath = resolveSampleDir(sampleId).resolve("video/face.mp4").normalize();
        if (!videoPath.startsWith(resolveSampleDir(sampleId)) || !Files.isRegularFile(videoPath)) {
            throw new IllegalArgumentException("样本视频不存在");
        }
        return new FileSystemResource(videoPath);
    }

    private Map<String, MultipartFile> normalizeFiles(MultipartFile[] files) {
        List<FileEntry> entries = new ArrayList<>();
        for (MultipartFile file : files) {
            if (file == null || file.isEmpty()) {
                throw new IllegalArgumentException("样本文件不能为空");
            }
            String original = normalizeRelativePath(file.getOriginalFilename());
            if (!StringUtils.hasText(original)) {
                throw new IllegalArgumentException("样本文件名不能为空");
            }
            entries.add(new FileEntry(original, file));
        }

        String rootPrefix = findRootPrefix(entries);
        if (rootPrefix.contains("/")) {
            throw new IllegalArgumentException("请选择单个系统样本目录，不要选择样本的上层目录");
        }
        Map<String, MultipartFile> normalized = new LinkedHashMap<>();
        for (FileEntry entry : entries) {
            String relative = stripRootPrefix(entry.relativePath, rootPrefix);
            validateRelativePath(relative);
            normalized.put(relative, entry.file);
        }
        return normalized;
    }

    private String findRootPrefix(List<FileEntry> entries) {
        for (FileEntry entry : entries) {
            if (entry.relativePath.equals("manifest.json")) {
                return "";
            }
            if (entry.relativePath.endsWith("/manifest.json")) {
                return entry.relativePath.substring(0, entry.relativePath.length() - "/manifest.json".length());
            }
        }
        return "";
    }

    private String stripRootPrefix(String path, String rootPrefix) {
        if (!StringUtils.hasText(rootPrefix)) {
            return path;
        }
        return path.startsWith(rootPrefix + "/") ? path.substring(rootPrefix.length() + 1) : path;
    }

    private String normalizeRelativePath(String value) {
        return defaultString(value, "").replace('\\', '/').replaceAll("^/+", "").trim();
    }

    private void validateRelativePath(String relativePath) {
        if (!StringUtils.hasText(relativePath) || relativePath.contains("..") || relativePath.startsWith("/")) {
            throw new IllegalArgumentException("样本文件路径非法: " + relativePath);
        }
        Path normalized = Path.of(relativePath).normalize();
        if (normalized.isAbsolute() || normalized.startsWith("..")) {
            throw new IllegalArgumentException("样本文件路径非法: " + relativePath);
        }
    }

    private boolean isAllowedFile(String relativePath) {
        String lower = relativePath.toLowerCase();
        return ALLOWED_SUFFIXES.stream().anyMatch(lower::endsWith);
    }

    private void validatePayloads(Map<String, MultipartFile> files) {
        try {
            objectMapper.readTree(files.get("manifest.json").getInputStream());
            objectMapper.readTree(files.get("eeg/raw_wave.json").getInputStream());
            objectMapper.readTree(files.get("eeg/raw_tgam.json").getInputStream());
            validateJsonLines("eeg/predictions.jsonl", files.get("eeg/predictions.jsonl"));
            validateJsonLines("face/predictions.jsonl", files.get("face/predictions.jsonl"));
        } catch (IOException e) {
            throw new DemoSampleValidationException("样本文件格式无法解析", List.of(e.getMessage()));
        }
    }

    private void validateJsonLines(String path, MultipartFile file) throws IOException {
        int count = 0;
        try (BufferedReader reader = new BufferedReader(new java.io.InputStreamReader(file.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!StringUtils.hasText(line)) {
                    continue;
                }
                objectMapper.readTree(line);
                count += 1;
            }
        }
        if (count == 0) {
            throw new IOException(path + " 不能为空");
        }
    }

    private Path resolveSampleDir(String sampleId) {
        if (!StringUtils.hasText(sampleId) || !sampleId.matches("[A-Za-z0-9_.-]+")) {
            throw new IllegalArgumentException("样本编号非法");
        }
        Path sampleDir = sampleRoot.resolve(sampleId).normalize();
        if (!sampleDir.startsWith(sampleRoot.normalize())) {
            throw new IllegalArgumentException("样本路径非法");
        }
        return sampleDir;
    }

    private JsonNode readLastJsonLine(Path path) throws IOException {
        JsonNode latest = null;
        try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!StringUtils.hasText(line)) {
                    continue;
                }
                latest = objectMapper.readTree(line);
            }
        }
        return latest;
    }

    private List<JsonNode> readJsonLines(Path path) throws IOException {
        List<JsonNode> result = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!StringUtils.hasText(line)) {
                    continue;
                }
                result.add(objectMapper.readTree(line));
            }
        }
        return result;
    }

    private Map<String, Object> buildRawWave(JsonNode rawWave) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workerId", rawWave.path("workerId").asInt(0));
        result.put("waveFs", rawWave.path("waveFs").asInt(0));
        result.put("windowStart", rawWave.path("windowStart").asLong(0));
        result.put("windowEnd", rawWave.path("windowEnd").asLong(0));
        result.put("samples", objectMapper.convertValue(rawWave.path("samples"), List.class));
        return result;
    }

    private Map<String, Object> buildRawTgam(JsonNode rawTgam) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("workerId", rawTgam.path("workerId").asInt(0));
        result.put("rawTgamFs", rawTgam.path("rawTgamFs").asInt(0));
        result.put("windowStart", rawTgam.path("windowStart").asLong(0));
        result.put("windowEnd", rawTgam.path("windowEnd").asLong(0));
        result.put("targetWindowStart", rawTgam.path("targetWindowStart").asLong(0));
        result.put("targetWindowEnd", rawTgam.path("targetWindowEnd").asLong(0));
        result.put("partial", rawTgam.path("partial").asBoolean(false));
        result.put("sampleCount", rawTgam.path("sampleCount").asInt(rawTgam.path("samples").size()));
        result.put("samples", objectMapper.convertValue(rawTgam.path("samples"), List.class));
        return result;
    }

    private List<Map<String, Object>> buildEegTimeline(List<JsonNode> predictions) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (JsonNode prediction : predictions) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("time", readPredictionTime(prediction));
            item.put("emotion", prediction.path("emotion").asText(""));
            item.put("emotionZh", prediction.path("emotion_zh").asText(""));
            item.put("raw_powers", objectMapper.convertValue(prediction.path("raw_powers"), Map.class));
            result.add(item);
        }
        return result;
    }

    private long readPredictionTime(JsonNode prediction) {
        String[] fields = {"analysis_ts", "analysisTime", "timestamp", "ts", "time"};
        for (String field : fields) {
            JsonNode value = prediction.path(field);
            if (value.isNumber()) {
                return value.asLong();
            }
            if (value.isTextual() && StringUtils.hasText(value.asText())) {
                try {
                    return Long.parseLong(value.asText().trim());
                } catch (NumberFormatException ignored) {
                    // Try the next known timestamp field.
                }
            }
        }
        return 0;
    }

    private String defaultString(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private record FileEntry(String relativePath, MultipartFile file) {
    }

    public static class DemoSampleValidationException extends IllegalArgumentException {
        private final List<String> missing;

        public DemoSampleValidationException(String message, List<String> missing) {
            super(message);
            this.missing = missing;
        }

        public List<String> getMissing() {
            return missing;
        }
    }
}
