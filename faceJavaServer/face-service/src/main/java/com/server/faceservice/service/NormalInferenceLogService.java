package com.server.faceservice.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.NormalInferenceLog;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

@Service
public class NormalInferenceLogService {
    private static final Logger log = LoggerFactory.getLogger(NormalInferenceLogService.class);
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE;

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Path logRoot;
    private final ZoneId zoneId;
    private final int retentionDays;

    public NormalInferenceLogService(
            @Value("${app.normal-inference-log.dir:logs/normal-inference}") String logDir,
            @Value("${app.normal-inference-log.zone-id:Asia/Shanghai}") String configuredZoneId,
            @Value("${app.normal-inference-log.retention-days:4}") int retentionDays
    ) {
        this.logRoot = Path.of(logDir);
        this.zoneId = ZoneId.of(StringUtils.hasText(configuredZoneId) ? configuredZoneId : "Asia/Shanghai");
        this.retentionDays = Math.max(1, retentionDays);
    }

    public synchronized NormalInferenceLog append(NormalInferenceLog input) {
        NormalInferenceLog normalized = normalize(input);
        Path file = resolveFile(Instant.ofEpochMilli(normalized.getTimestamp()).atZone(zoneId).toLocalDate());
        try {
            cleanupExpired();
            Path parent = file.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            String line = objectMapper.writeValueAsString(normalized) + System.lineSeparator();
            Files.writeString(file, line, StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            return normalized;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to append normal inference log: " + file, e);
        }
    }

    private NormalInferenceLog normalize(NormalInferenceLog input) {
        NormalInferenceLog item = input == null ? new NormalInferenceLog() : input;
        long timestamp = item.getTimestamp() > 0 ? item.getTimestamp() : System.currentTimeMillis();
        LocalDate date = Instant.ofEpochMilli(timestamp).atZone(zoneId).toLocalDate();

        item.setTimestamp(timestamp);
        item.setDate(date.format(DATE_FORMATTER));
        item.setId(StringUtils.hasText(item.getId()) ? item.getId().trim() : "normal_" + UUID.randomUUID().toString().replace("-", ""));
        item.setPersonId(defaultString(item.getPersonId(), ""));
        item.setPersonName(defaultString(item.getPersonName(), "unbound"));
        item.setCameraId(defaultString(item.getCameraId(), ""));
        item.setFusionEmotion(defaultString(item.getFusionEmotion(), "normal"));
        item.setFaceEmotion(defaultString(item.getFaceEmotion(), ""));
        item.setEegEmotion(defaultString(item.getEegEmotion(), ""));
        item.setConfidence(Math.max(0, Math.min(100, item.getConfidence())));
        item.setSampleCounts(normalizeSampleCounts(item.getSampleCounts()));
        item.setMessage(defaultString(item.getMessage(), "normal inference alive"));
        return item;
    }

    private Map<String, Integer> normalizeSampleCounts(Map<String, Integer> sampleCounts) {
        Map<String, Integer> normalized = new HashMap<>();
        if (sampleCounts != null) {
            normalized.putAll(sampleCounts);
        }
        normalized.putIfAbsent("eeg", 0);
        normalized.putIfAbsent("face", 0);
        return normalized;
    }

    private void cleanupExpired() throws IOException {
        if (!Files.exists(logRoot)) {
            return;
        }
        LocalDate cutoff = LocalDate.now(zoneId).minusDays(retentionDays - 1L);
        try (Stream<Path> files = Files.find(logRoot, 4, (path, attrs) -> attrs.isRegularFile() && path.getFileName().toString().endsWith(".jsonl"))) {
            files.forEach(path -> {
                LocalDate fileDate = parseLogDate(path);
                if (fileDate == null || !fileDate.isBefore(cutoff)) {
                    return;
                }
                try {
                    Files.deleteIfExists(path);
                } catch (IOException e) {
                    log.warn("Failed to delete expired normal inference log {}: {}", path.toAbsolutePath(), e.getMessage());
                }
            });
        }
    }

    private LocalDate parseLogDate(Path path) {
        String name = path.getFileName().toString();
        if (!name.endsWith(".jsonl")) {
            return null;
        }
        try {
            return LocalDate.parse(name.substring(0, name.length() - ".jsonl".length()), DATE_FORMATTER);
        } catch (Exception e) {
            return null;
        }
    }

    private Path resolveFile(LocalDate date) {
        return logRoot
                .resolve(String.format("%04d", date.getYear()))
                .resolve(String.format("%02d", date.getMonthValue()))
                .resolve(date.format(DATE_FORMATTER) + ".jsonl");
    }

    private String defaultString(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }
}
