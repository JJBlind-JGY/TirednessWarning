package com.server.faceservice.config;

import com.server.faceservice.service.FaceDetectService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

@Component
public class VideoStreamAutoRunner {

    private static final Logger log = LoggerFactory.getLogger(VideoStreamAutoRunner.class);

    @Autowired
    private FaceDetectService faceDetectService;

    // 从 application.yml/properties 中读取配置，避免硬编码
    @Value("${app.rtsp.url}")
    private String rtspUrl;

    @Value("${app.user.id:default_user}")
    private String userId;

    /**
     * 监听应用启动完成事件
     * 当 Spring Boot 完全启动后，自动执行此方法
     */
    @EventListener(ApplicationReadyEvent.class)
    public void startVideoStreamTask() {
        log.info("应用启动完成，准备开启 RTSP 视频流自动拉取任务...");
        log.info("RTSP 地址: {}", rtspUrl);

        // 启动一个独立的后台线程来运行拉流逻辑
        Thread streamThread = new Thread(() -> {
            // 无限循环：保证流断了之后能自动重连
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    log.info("正在尝试连接视频流...");
                    // 调用你的业务逻辑开始拉流
                    faceDetectService.processVideo(rtspUrl, userId);
                } catch (Exception e) {
                    log.error("视频流连接或处理异常，5秒后尝试重连...", e);
                    try {
                        // 异常后等待一段时间再重连，避免瞬间重试把摄像头搞挂
                        Thread.sleep(5000);
                    } catch (InterruptedException ie) {
                        log.warn("重连等待被中断，退出任务");
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            }
            log.warn("RTSP 拉流任务已停止");
        });

        // 设置线程名称，方便调试
        streamThread.setName("RTSP-Stream-Thread");
        // 设置为守护线程：当主程序关闭时，这个线程也会自动关闭
        streamThread.setDaemon(true);
        // 启动线程
        streamThread.start();
    }
}