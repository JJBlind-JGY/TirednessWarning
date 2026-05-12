package com.server.faceservice.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.AlertLog;
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
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;

@Service
public class AlertLogService {
    private static final Logger log = LoggerFactory.getLogger(AlertLogService.class);
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE;
    private static final Set<String> ALLOWED_TYPES = Set.of("abnormal_start", "recovered", "eye_closed_danger");

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Path logRoot;
    private final ZoneId zoneId;

    public AlertLogService(
            @Value("${app.alert-log.dir:logs/alerts}") String logDir,
            @Value("${app.alert-log.zone-id:Asia/Shanghai}") String configuredZoneId
    ) {
        this.logRoot = Path.of(logDir);
        this.zoneId = ZoneId.of(StringUtils.hasText(configuredZoneId) ? configuredZoneId : "Asia/Shanghai");
    }

    public synchronized List<AlertLog> listToday() {
        return list(LocalDate.now(zoneId));
    }

    public synchronized List<AlertLog> list(String date) {
        return list(parseDate(date));
    }

    public synchronized AlertLog append(AlertLog input) {
        AlertLog normalized = normalize(input);
        Path file = resolveFile(parseDate(normalized.getDate()));
        try {
            Path parent = file.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            String line = objectMapper.writeValueAsString(normalized) + System.lineSeparator();
            Files.writeString(file, line, StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            return normalized;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to append alert log: " + file, e);
        }
    }

    private List<AlertLog> list(LocalDate date) {
        Path file = resolveFile(date);
        if (!Files.exists(file)) {
            return new ArrayList<>();
        }

        List<AlertLog> logs = new ArrayList<>();
        try {
            List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
            for (String line : lines) {
                if (!StringUtils.hasText(line)) {
                    continue;
                }
                try {
                    logs.add(objectMapper.readValue(line, AlertLog.class));
                } catch (Exception e) {
                    log.warn("Skip malformed alert log line in {}: {}", file.toAbsolutePath(), e.getMessage());
                }
            }
            logs.sort((a, b) -> Long.compare(b.getTimestamp(), a.getTimestamp()));
            return logs;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read alert log: " + file, e);
        }
    }

    private AlertLog normalize(AlertLog input) {
        AlertLog log = input == null ? new AlertLog() : input;
        long timestamp = log.getTimestamp() > 0 ? log.getTimestamp() : System.currentTimeMillis();
        LocalDate date = StringUtils.hasText(log.getDate())
                ? parseDate(log.getDate())
                : Instant.ofEpochMilli(timestamp).atZone(zoneId).toLocalDate();

        log.setTimestamp(timestamp);
        log.setDate(date.format(DATE_FORMATTER));
        log.setId(StringUtils.hasText(log.getId()) ? log.getId().trim() : "alert_" + UUID.randomUUID().toString().replace("-", ""));
        log.setPersonName(defaultString(log.getPersonName(), "未绑定人员"));
        log.setPersonId(defaultString(log.getPersonId(), ""));
        log.setDevice(defaultString(log.getDevice(), "未配置设备"));
        log.setLevel(defaultString(log.getLevel(), "warning"));
        log.setMessage(defaultString(log.getMessage(), ""));

        String type = defaultString(log.getType(), "abnormal_start");
        if (!ALLOWED_TYPES.contains(type)) {
            throw new IllegalArgumentException("Unsupported alert log type: " + type);
        }
        log.setType(type);
        return log;
    }

    private String defaultString(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private LocalDate parseDate(String date) {
        try {
            return LocalDate.parse(date, DATE_FORMATTER);
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("Date must be yyyy-MM-dd");
        }
    }

    private Path resolveFile(LocalDate date) {
        return logRoot
                .resolve(String.format("%04d", date.getYear()))
                .resolve(String.format("%02d", date.getMonthValue()))
                .resolve(date.format(DATE_FORMATTER) + ".jsonl");
    }
}
