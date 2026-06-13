package com.server.faceservice.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.server.faceservice.config.CameraConfig;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CameraConfigServiceTests {
    private CameraConfigService service() {
        return new CameraConfigService("camera-config-test.json", "go2rtc-test.yaml", "");
    }

    @Test
    void localCameraDefaultsToDeviceZeroWithoutRtspUrl() {
        CameraConfig input = new CameraConfig();
        input.setId("local_camera");
        input.setName("Local camera");
        input.setSourceType("local");

        CameraConfig normalized = service().normalize(input);

        assertTrue(normalized.isLocal());
        assertEquals(0, normalized.getDeviceIndex());
        assertEquals("", normalized.getRtspUrl());
    }

    @Test
    void legacyCameraDefaultsToRtsp() {
        CameraConfig input = new CameraConfig();
        input.setId("camera_01");
        input.setRtspUrl("rtsp://192.168.1.8/live");

        CameraConfig normalized = service().normalize(input);

        assertEquals("rtsp", normalized.getSourceType());
        assertEquals("rtsp://192.168.1.8/live", normalized.getRtspUrl());
    }

    @Test
    void rtspCameraRequiresUrl() {
        CameraConfig input = new CameraConfig();
        input.setId("camera_01");
        input.setSourceType("rtsp");

        assertThrows(IllegalArgumentException.class, () -> service().normalize(input));
    }

    @Test
    void localCameraRejectsNegativeDeviceIndex() {
        CameraConfig input = new CameraConfig();
        input.setId("local_camera");
        input.setSourceType("local");
        input.setDeviceIndex(-1);

        assertThrows(IllegalArgumentException.class, () -> service().normalize(input));
    }

    @Test
    void localHelperIsNotSerializedAsConfigurationField() throws Exception {
        CameraConfig camera = new CameraConfig("local", "Local", "local", 0, "", "local");
        String json = new ObjectMapper().writeValueAsString(camera);

        assertTrue(!json.contains("\"local\":"));
        assertTrue(json.contains("\"sourceType\":\"local\""));
    }

    @Test
    void localCameraUsesGo2RtcFfmpegDeviceSource() {
        CameraConfig camera = new CameraConfig("local", "Local", "local", 0, "", "local");

        assertEquals(
                "ffmpeg:device?video=0&video_size=1280x720&framerate=30#video=h264",
                CameraConfigService.streamSource(camera)
        );
        assertEquals("rtsp://127.0.0.1:8554/local?video=h264", service().modelInputUrl(camera));
    }
}
