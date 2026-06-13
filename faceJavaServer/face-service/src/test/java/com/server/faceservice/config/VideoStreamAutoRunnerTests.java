package com.server.faceservice.config;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class VideoStreamAutoRunnerTests {
    @Test
    void localSourceKeyUsesDeviceIndex() {
        CameraConfig camera = new CameraConfig("local", "Local", "local", 2, "", "local");
        assertEquals("local:2", VideoStreamAutoRunner.cameraSourceKey(camera));
    }

    @Test
    void rtspSourceKeyUsesUrl() {
        CameraConfig camera = new CameraConfig("remote", "Remote", "rtsp", 0, "rtsp://host/live", "remote");
        assertEquals("rtsp:rtsp://host/live", VideoStreamAutoRunner.cameraSourceKey(camera));
    }
}
