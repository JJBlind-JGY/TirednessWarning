package com.server.faceservice.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class AlertLogTests {
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void readsLegacyAlertLogWithoutDiagnostics() throws Exception {
        AlertLog log = objectMapper.readValue("""
                {
                  "id": "legacy-alert",
                  "timestamp": 123456789,
                  "type": "abnormal_start",
                  "message": "legacy"
                }
                """, AlertLog.class);

        assertEquals("legacy-alert", log.getId());
        assertEquals("abnormal_start", log.getType());
        assertNull(log.getDiagnostics());
    }

    @Test
    void preservesFatigueDiagnostics() throws Exception {
        AlertLog input = new AlertLog();
        input.setId("fatigue-alert");
        input.setType("fatigue_diagnostic");
        input.setDiagnostics(Map.of(
                "triggerReason", "eye_closed",
                "windowMs", 20000
        ));

        AlertLog output = objectMapper.readValue(objectMapper.writeValueAsString(input), AlertLog.class);

        assertEquals("eye_closed", output.getDiagnostics().get("triggerReason"));
        assertEquals(20000, output.getDiagnostics().get("windowMs"));
    }
}
