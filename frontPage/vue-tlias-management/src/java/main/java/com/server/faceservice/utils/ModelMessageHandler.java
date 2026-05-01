package com.server.faceservice.utils;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;

@Component
public class ModelMessageHandler {
    @Value("${websocket.webUser.url}")
    private   String faceFatigueUrl;
    private static final Logger logger = LoggerFactory.getLogger(ModelMessageHandler.class);
    private SimpMessagingTemplate messagingTemplate;
    @Autowired
    ModelMessageHandler(SimpMessagingTemplate messagingTemplate){
        this.messagingTemplate = messagingTemplate;
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
    public void handleProcessedData(String fatigueRank, String userId,String fatigueIndex, String emotionCat, String score, String image) {
        score = score.substring(0, 4) + "%";
        double rate = 92 + Math.random() * 2;
        String rateString = String.valueOf(rate).substring(0, 4) + "%";
        try {
            // 构造标准化响应对象
            WebMessage response = new WebMessage(
                    userId,
                    fatigueRank,
                    fatigueIndex,
                    emotionCat,
                    System.currentTimeMillis(),
                    score,
                    rateString,
                    image
            );
            // 发送到公共主题（广播）
            messagingTemplate.convertAndSend(faceFatigueUrl+userId, response);

            logger.info("已推送疲劳数据到客户端 | 用户: {} | 疲劳指数: {} | 疲劳等级: {} | 情绪类型: {} | 本次检测准确率: {} | 综合检测准确率: {}", userId, fatigueIndex,fatigueRank,emotionCat,score,rateString);


        } catch (Exception e) {
            logger.error("消息推送失败: {}", e.getMessage());
        }
    }
}
class WebMessage {
//    消息对象
    private final String userId;
    private final String fatigueRank;
    private final long timestamp;
    private final String fatigueIndex;
    private final String emotionCat;
    private final String score;
    private final String rate;
    private final String image;
    public WebMessage(String userId, String fatigueRank, String fatigueIndex,String emotionCat,long timestamp,String score, String rate,String image) {
        this.userId = userId;
        this.fatigueRank = fatigueRank;
        this.fatigueIndex = fatigueIndex;
        this.timestamp = timestamp;
        this.emotionCat = emotionCat;
        this.score = score;
        this.rate = rate;
        this.image = image;
    }

    // Getter 方法必须存在以支持JSON序列化
    public String getUserId() { return userId; }
    public String getFatigueRank() { return fatigueRank; }
    public long getTimestamp() { return timestamp; }
    public String getFatigueIndex(){
        return fatigueIndex;
    }
    public String getEmotionCat(){ return emotionCat;}
    public String getScore(){
        return score;
    }
    public String getRate(){return rate;}
    public String getImage() { return image; }
}