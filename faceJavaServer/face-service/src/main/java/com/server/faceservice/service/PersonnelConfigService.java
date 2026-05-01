package com.server.faceservice.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.PersonnelConfig;
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
public class PersonnelConfigService {
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Path configPath;

    public PersonnelConfigService(@Value("${app.personnel.config-file:personnel-config.json}") String configFile) {
        this.configPath = Path.of(configFile);
    }

    public synchronized List<PersonnelConfig> list() {
        if (!Files.exists(configPath)) {
            List<PersonnelConfig> initial = new ArrayList<>();
            save(initial);
            return initial;
        }

        try {
            List<PersonnelConfig> personnel = objectMapper.readValue(
                    configPath.toFile(),
                    new TypeReference<List<PersonnelConfig>>() {
                    }
            );
            return personnel == null ? new ArrayList<>() : personnel;
        } catch (IOException e) {
            throw new IllegalStateException("Failed to read personnel config: " + configPath, e);
        }
    }

    public synchronized PersonnelConfig upsert(PersonnelConfig personnel) {
        PersonnelConfig normalized = normalize(personnel);
        List<PersonnelConfig> list = list();
        Optional<PersonnelConfig> existing = list.stream()
                .filter(item -> item.getId().equals(normalized.getId()))
                .findFirst();

        if (existing.isPresent()) {
            PersonnelConfig target = existing.get();
            target.setUid(normalized.getUid());
            target.setName(normalized.getName());
            target.setType(normalized.getType());
        } else {
            list.add(normalized);
        }

        save(list);
        return normalized;
    }

    public synchronized boolean remove(String personnelId) {
        List<PersonnelConfig> list = list();
        boolean removed = list.removeIf(item -> item.getId().equals(personnelId));
        if (removed) {
            save(list);
        }
        return removed;
    }

    private PersonnelConfig normalize(PersonnelConfig personnel) {
        String id = StringUtils.hasText(personnel.getId()) ? personnel.getId().trim() : "person_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String uid = StringUtils.hasText(personnel.getUid()) ? personnel.getUid().trim() : id;
        String name = StringUtils.hasText(personnel.getName()) ? personnel.getName().trim() : "";
        String type = StringUtils.hasText(personnel.getType()) ? personnel.getType().trim() : "";
        if (!StringUtils.hasText(name)) {
            throw new IllegalArgumentException("Personnel name is required");
        }
        if (!StringUtils.hasText(uid)) {
            throw new IllegalArgumentException("Personnel uid is required");
        }
        return new PersonnelConfig(id, uid, name, type);
    }

    private void save(List<PersonnelConfig> personnel) {
        try {
            Path parent = configPath.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(configPath.toFile(), personnel);
        } catch (IOException e) {
            throw new IllegalStateException("Failed to write personnel config: " + configPath, e);
        }
    }
}
