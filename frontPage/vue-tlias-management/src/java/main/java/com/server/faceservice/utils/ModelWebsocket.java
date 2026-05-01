package com.server.faceservice.utils;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.net.URI;
import java.security.KeyManagementException;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;

@Component
public class ModelWebsocket extends WebSocketClient {
    private  CountDownLatch connectionLatch = new CountDownLatch(1);
    private static final Logger LOGGER = LoggerFactory.getLogger(ModelWebsocket.class);
    private long retryCount = 0;
    private static final int MAX_RETRIES = 1000000;
    // 最大重连延迟（30秒），避免延迟过大
    private static final long MAX_RECONNECT_DELAY_MS = 30000;
    // 初始重连延迟（1秒）
    private static final long INITIAL_RECONNECT_DELAY_MS = 1000;
    private volatile boolean isReconnecting = false;
    public boolean isConnected = true;
    private  final boolean shouldReconnect = true;


    public ModelWebsocket(URI serverUri) throws Exception {
        super(serverUri);
        LOGGER.info("ModelWebsocket initialized with URI: {}", serverUri);
    }

    @Autowired
    @Qualifier("websocketExecutor")
    private ExecutorService websocketExecutor;
    @Autowired
    ModelMessageHandler modelMessageHandler;
    @Override
    public void onOpen(ServerHandshake arg0) {
        connectionLatch.countDown();
        isConnected = true;
        retryCount = 0;
        isReconnecting = false;
        LOGGER.info("----------------------- modelSocket onOpen ------------------------------");
    }

    @Override
    public void onClose(int arg0, String arg1, boolean arg2) {
        isConnected = false;
        connectionLatch.countDown();
        LOGGER.info("------ modelSocket onClose ------{}",arg1);
        if (shouldReconnect && !isReconnecting && (retryCount < MAX_RETRIES)) {
            isReconnecting = true;
//            new Thread(this::reconnectWithRetry, "ModelWebsocket-Reconnect-Thread").start();
//            reconnectWithRetry();
            websocketExecutor.submit(this::reconnectWithRetry);
        }

    }

    @Override
    public void onError(Exception arg0) {
        isConnected = false;
        connectionLatch.countDown();
    }

    @Override
    public void onMessage(String message) {

        LOGGER.info("-------- 接收到服务端数据  --------");
        websocketExecutor.submit(() -> {
            try {
                // 解析原始消息
                JSONObject json = JSON.parseObject(message);

                int emotionId = Integer.parseInt(json.get("emotionId").toString());
//                if(emotionId == -1) {
//                    LOGGER.info("未检测到人脸");
//                    return;
//                }
                String image = json.get("image").toString();
                String arousal = json.get("arousal").toString();
                String userId = json.get("userId").toString();
                double temp = Double.parseDouble(arousal);
                String score = json.getString("score");
                String fatigueRank = "0";
                if (temp < 4 && temp > 2.5) {
                    fatigueRank = "1";
                } else if (temp <= 2.5 && temp > 1.5) {
                    fatigueRank = "2";
                } else if (temp <= 1.5) {
                    fatigueRank = "3";
                }
                String emotionCat = "其它";
                if (emotionId == 0) {
                    emotionCat = "虚弱";
                } else if (emotionId == 1) {
                    emotionCat = "疲劳";
                } else if (emotionId == 2) {
                    emotionCat = "紧张";
                } else if (emotionId == 3) {
                    emotionCat = "焦躁";
                }
                String fatigueIndex = String.valueOf(10 - temp);
                // 调用处理器进行后续处理
                modelMessageHandler.handleProcessedData(fatigueRank, userId, fatigueIndex, emotionCat, score,image);

            } catch (Exception e) {
                LOGGER.error("消息处理失败: {}", e.getMessage());
            }
        });

    }
    private void reconnectWithRetry() {

            try {
                while (retryCount < MAX_RETRIES) {
                    retryCount++;
                    LOGGER.info("尝试重连模型，第{}次", retryCount);
                    long temp = (1000L * (retryCount - 1) + INITIAL_RECONNECT_DELAY_MS);
                    Thread.sleep(Math.min(temp, MAX_RECONNECT_DELAY_MS));
                    //上锁
                    connectionLatch = new CountDownLatch(1);
                    reconnect();
                    connectionLatch.await();
                    if (isConnected) {
                        LOGGER.info("重连成功");
                        return;
                    } else {
                        LOGGER.warn("第{}次重连失败", retryCount);
                    }
                }
            } catch (InterruptedException e) {
                LOGGER.warn("重连线程被中断，线程名：{}，调用栈：", Thread.currentThread().getName(), e);
                Thread.currentThread().interrupt();
            } catch (Exception e) {
                LOGGER.warn("第{}次重连失败：{}", retryCount, e.getMessage(), e); // 打印完整异常
            }
        isReconnecting = false; // 重连结束（成功或达到最大次数），重置标志
        LOGGER.error("自动重连失败{}次，请尝试重启服务", MAX_RETRIES);
    }
    // 在ModelWebsocket的构造方法或连接逻辑中添加SSL配置
    private SSLContext createIgnoreVerifySSL() throws NoSuchAlgorithmException, KeyManagementException {
        SSLContext sc = SSLContext.getInstance("TLS");
        // 实现一个不验证证书链的TrustManager
        TrustManager tm = new X509TrustManager() {
            @Override
            public java.security.cert.X509Certificate[] getAcceptedIssuers() {
                return null;
            }
            @Override
            public void checkClientTrusted(java.security.cert.X509Certificate[] chain, String authType) {
            }
            @Override
            public void checkServerTrusted(java.security.cert.X509Certificate[] chain, String authType) {
            }
        };
        sc.init(null, new TrustManager[]{tm}, new java.security.SecureRandom());
        return sc;
    }

    // 修改连接逻辑，使用自定义SSLContext
    @Override
    public void connect() {
        try {
            if (getURI().getScheme().equals("wss")) {
                SSLContext sslContext = createIgnoreVerifySSL();
                SSLSocketFactory factory = sslContext.getSocketFactory();
                // 为Java-WebSocket客户端设置SSL工厂
                this.setSocket(factory.createSocket());

            }
            super.connect();
        } catch (Exception e) {
            LOGGER.error("SSL连接初始化失败", e);
        }
    }
}