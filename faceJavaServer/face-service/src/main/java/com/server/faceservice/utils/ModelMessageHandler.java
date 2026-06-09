package com.server.faceservice.utils;

import com.alibaba.fastjson.JSONObject;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;
import com.server.faceservice.service.AbnormalSampleService;

@Component
public class ModelMessageHandler {
    @Value("${websocket.webUser.url}")
    private String faceFatigueUrl;

    private static final Logger logger = LoggerFactory.getLogger(ModelMessageHandler.class);
    private final SimpMessagingTemplate messagingTemplate;
    private final AbnormalSampleService abnormalSampleService;

    @Autowired
    ModelMessageHandler(SimpMessagingTemplate messagingTemplate, AbnormalSampleService abnormalSampleService) {
        this.messagingTemplate = messagingTemplate;
        this.abnormalSampleService = abnormalSampleService;
    }

    @PostConstruct
    public void init() {
        if (faceFatigueUrl == null) {
            logger.error("faceFatigueUrl is null");
        }
        if (messagingTemplate == null) {
            logger.error("messagingTemplate is null");
        }
    }

    public void handleModelPayload(JSONObject json) {
        String userId = json.getString("userId");
        if (userId == null || userId.isBlank()) {
            logger.warn("drop face model payload without userId");
            return;
        }

        WebMessage response = toWebMessage(json, System.currentTimeMillis());
        abnormalSampleService.recordFacePrediction(json);
        messagingTemplate.convertAndSend(faceFatigueUrl + userId, response);
        logger.info("face model result pushed: userId={}, status={}, emotion5={}, emotionCat={}, score={}",
                userId, response.getStatus(), response.getEmotion5(), response.getEmotionCat(), response.getScore());
    }

    public void handleProcessedData(String fatigueRank, String userId, String fatigueIndex, String emotionCat, String score, String image) {
        JSONObject json = new JSONObject();
        json.put("userId", userId);
        json.put("status", "ok");
        json.put("emotionCat", emotionCat);
        json.put("score", score);
        json.put("fatigueIndex", fatigueIndex);
        json.put("fatigueRank", fatigueRank);
        json.put("image", image);
        handleModelPayload(json);
    }

    static WebMessage toWebMessage(JSONObject json, long timestamp) {
        return new WebMessage(
                json.getString("userId"),
                valueOrDefault(json.getString("status"), "ok"),
                json.getString("emotion5"),
                json.getString("emotionCat"),
                normalizeScore(json.get("score")),
                normalizeNumber(json.get("fatigueIndex")),
                normalizeNumber(json.get("fatigueRank")),
                json.get("faceBox"),
                json.get("scores7"),
                json.getString("eyeStatus"),
                json.getBoolean("eyeClosed"),
                normalizeScore(json.get("eyeClosedScore")),
                normalizeScore(json.get("eyeOpenScore")),
                json.get("eyeBoxes"),
                json.get("eyeCheckedAt"),
                json.getBoolean("mouthOpen"),
                normalizeScore(json.get("yawnScore")),
                json.get("mouthCheckedAt"),
                timestamp,
                json.getString("image")
        );
    }

    private static String valueOrDefault(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String normalizeNumber(Object value) {
        return value == null ? "--" : String.valueOf(value);
    }

    private static String normalizeScore(Object value) {
        if (value == null) {
            return "--";
        }
        try {
            double numeric = Double.parseDouble(String.valueOf(value).replace("%", ""));
            return String.format("%.1f", numeric);
        } catch (Exception e) {
            String score = String.valueOf(value);
            return score.isBlank() ? "--" : score.replace("%", "");
        }
    }
}

class WebMessage {
    private final String userId;
    private final String status;
    private final String emotion5;
    private final String emotionCat;
    private final String score;
    private final String fatigueIndex;
    private final String fatigueRank;
    private final Object faceBox;
    private final Object scores7;
    private final String eyeStatus;
    private final Boolean eyeClosed;
    private final String eyeClosedScore;
    private final String eyeOpenScore;
    private final Object eyeBoxes;
    private final Object eyeCheckedAt;
    private final Boolean mouthOpen;
    private final String yawnScore;
    private final Object mouthCheckedAt;
    private final long timestamp;
    private final String image;

    public WebMessage(String userId, String status, String emotion5, String emotionCat, String score,
                      String fatigueIndex, String fatigueRank, Object faceBox, Object scores7,
                      String eyeStatus, Boolean eyeClosed, String eyeClosedScore, String eyeOpenScore,
                      Object eyeBoxes, Object eyeCheckedAt,
                      Boolean mouthOpen, String yawnScore, Object mouthCheckedAt,
                      long timestamp, String image) {
        this.userId = userId;
        this.status = status;
        this.emotion5 = emotion5;
        this.emotionCat = emotionCat;
        this.score = score;
        this.fatigueIndex = fatigueIndex;
        this.fatigueRank = fatigueRank;
        this.faceBox = faceBox;
        this.scores7 = scores7;
        this.eyeStatus = eyeStatus;
        this.eyeClosed = eyeClosed;
        this.eyeClosedScore = eyeClosedScore;
        this.eyeOpenScore = eyeOpenScore;
        this.eyeBoxes = eyeBoxes;
        this.eyeCheckedAt = eyeCheckedAt;
        this.mouthOpen = mouthOpen;
        this.yawnScore = yawnScore;
        this.mouthCheckedAt = mouthCheckedAt;
        this.timestamp = timestamp;
        this.image = image;
    }

    public String getUserId() { return userId; }
    public String getStatus() { return status; }
    public String getEmotion5() { return emotion5; }
    public String getEmotionCat() { return emotionCat; }
    public String getScore() { return score; }
    public String getFatigueIndex() { return fatigueIndex; }
    public String getFatigueRank() { return fatigueRank; }
    public Object getFaceBox() { return faceBox; }
    public Object getScores7() { return scores7; }
    public String getEyeStatus() { return eyeStatus; }
    public Boolean getEyeClosed() { return eyeClosed; }
    public String getEyeClosedScore() { return eyeClosedScore; }
    public String getEyeOpenScore() { return eyeOpenScore; }
    public Object getEyeBoxes() { return eyeBoxes; }
    public Object getEyeCheckedAt() { return eyeCheckedAt; }
    public Boolean getMouthOpen() { return mouthOpen; }
    public String getYawnScore() { return yawnScore; }
    public Object getMouthCheckedAt() { return mouthCheckedAt; }
    public long getTimestamp() { return timestamp; }
    public String getImage() { return image; }
}
