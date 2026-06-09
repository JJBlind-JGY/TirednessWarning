package com.server.faceservice.utils;

import com.alibaba.fastjson.JSONObject;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ModelMessageHandlerTests {

    @Test
    void forwardsEyeAndYawnFieldsWithoutChangingTheirMeaning() {
        JSONObject payload = new JSONObject();
        payload.put("userId", "worker-1");
        payload.put("status", "ok");
        payload.put("eyeStatus", "closed");
        payload.put("eyeClosed", true);
        payload.put("eyeClosedScore", 87.26);
        payload.put("eyeOpenScore", 12.74);
        payload.put("eyeCheckedAt", 123456789L);
        payload.put("mouthOpen", false);
        payload.put("yawnScore", 31.234);
        payload.put("mouthCheckedAt", 123456790L);

        WebMessage message = ModelMessageHandler.toWebMessage(payload, 123456791L);
        assertEquals("worker-1", message.getUserId());
        assertEquals("ok", message.getStatus());
        assertEquals("closed", message.getEyeStatus());
        assertTrue(message.getEyeClosed());
        assertEquals("87.3", message.getEyeClosedScore());
        assertEquals("12.7", message.getEyeOpenScore());
        assertEquals(123456789L, message.getEyeCheckedAt());
        assertFalse(message.getMouthOpen());
        assertEquals("31.2", message.getYawnScore());
        assertEquals(123456790L, message.getMouthCheckedAt());
        assertEquals(123456791L, message.getTimestamp());
    }
}
