package com.server.faceservice.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.Resource;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DemoSampleServiceTests {
    @TempDir
    Path tempDir;

    @Test
    void uploadReturnsOriginalTgamSamplesAndPlayableVideoResource() throws Exception {
        DemoSampleService service = new DemoSampleService(tempDir.toString());
        MultipartFile[] files = {
                jsonFile("sample/manifest.json", """
                        {"workerId":1,"windowMs":1000}
                        """),
                binaryFile("sample/video/face.mp4", new byte[]{0, 0, 0, 20, 102, 116, 121, 112}),
                jsonFile("sample/eeg/raw_wave.json", """
                        {"workerId":1,"waveFs":128,"windowStart":1000,"windowEnd":2000,"samples":[1,2]}
                        """),
                jsonFile("sample/eeg/raw_tgam.json", """
                        {
                          "workerId":1,
                          "rawTgamFs":512,
                          "windowStart":1000,
                          "windowEnd":2000,
                          "targetWindowStart":1000,
                          "targetWindowEnd":2000,
                          "partial":false,
                          "sampleCount":3,
                          "samples":[652,-2048,2047]
                        }
                        """),
                jsonFile("sample/eeg/predictions.jsonl", """
                        {"analysis_ts":2000,"emotion":"normal","raw_powers":{"delta":1}}
                        """),
                jsonFile("sample/face/predictions.jsonl", """
                        {"timestamp":2000,"emotion":"normal"}
                        """)
        };

        Map<String, Object> uploadResult = service.upload(files);
        String sampleId = (String) uploadResult.get("sampleId");
        @SuppressWarnings("unchecked")
        Map<String, Object> detail = (Map<String, Object>) uploadResult.get("sample");
        @SuppressWarnings("unchecked")
        Map<String, Object> rawTgam = (Map<String, Object>) detail.get("rawTgam");

        assertEquals(512, rawTgam.get("rawTgamFs"));
        assertEquals(3, rawTgam.get("sampleCount"));
        assertEquals(List.of(652, -2048, 2047), rawTgam.get("samples"));
        assertEquals(1000L, rawTgam.get("targetWindowStart"));
        assertEquals(2000L, rawTgam.get("targetWindowEnd"));

        Resource video = service.video(sampleId);
        assertTrue(video.exists());
        assertEquals(8, video.contentLength());
    }

    private MockMultipartFile jsonFile(String path, String content) {
        return new MockMultipartFile(
                "files",
                path,
                "application/json",
                content.strip().getBytes(StandardCharsets.UTF_8)
        );
    }

    private MockMultipartFile binaryFile(String path, byte[] content) {
        return new MockMultipartFile("files", path, "video/mp4", content);
    }
}
