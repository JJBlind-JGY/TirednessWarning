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
                        {"analysis_ts":1500,"emotion":"normal","raw_powers":{"delta":1}}
                        {"analysis_ts":2000,"emotion":"fatigue","raw_powers":{"delta":1},"indices":{"fatigue_idx":72.5},"features":{"theta_beta":2.1,"z":{"theta_beta":1.4}},"reason_codes":["theta_beta_supported"],"quality_level":"good","signal_quality":0,"valid_current":true,"attention":42,"meditation":61}
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

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> timeline = (List<Map<String, Object>>) detail.get("eegTimeline");
        assertEquals(2, timeline.size());
        assertEquals("normal", timeline.get(0).get("emotion"));
        assertTrue(((Map<?, ?>) timeline.get(0).get("features")).isEmpty());
        assertEquals("fatigue", timeline.get(1).get("emotion"));
        assertEquals("good", timeline.get(1).get("quality_level"));
        assertEquals(true, timeline.get(1).get("valid_current"));
        @SuppressWarnings("unchecked")
        Map<String, Object> features = (Map<String, Object>) timeline.get(1).get("features");
        assertEquals(2.1, ((Number) features.get("theta_beta")).doubleValue(), 0.001);
        assertEquals(1, detail.get("validPredictionCount"));
        @SuppressWarnings("unchecked")
        Map<String, Integer> thresholdCounts = (Map<String, Integer>) detail.get("thresholdCounts");
        @SuppressWarnings("unchecked")
        Map<String, Integer> dominantVotes = (Map<String, Integer>) detail.get("dominantVotes");
        assertEquals(1, thresholdCounts.get("fatigue"));
        assertEquals(1, dominantVotes.get("fatigue"));
        assertEquals(0, thresholdCounts.get("stress"));

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
