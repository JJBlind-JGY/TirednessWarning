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
    private CountDownLatch connectionLatch = new CountDownLatch(1);
    private static final Logger LOGGER = LoggerFactory.getLogger(ModelWebsocket.class);
    private long retryCount = 0;
    private static final int MAX_RETRIES = 1000000;
    private static final long MAX_RECONNECT_DELAY_MS = 30000;
    private static final long INITIAL_RECONNECT_DELAY_MS = 1000;
    private volatile boolean isReconnecting = false;
    private volatile boolean isConnected = false;
    private final boolean shouldReconnect = true;

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
        LOGGER.info("model websocket opened");
    }

    @Override
    public void onClose(int arg0, String arg1, boolean arg2) {
        isConnected = false;
        connectionLatch.countDown();
        LOGGER.info("model websocket closed: {}", arg1);
        if (shouldReconnect && !isReconnecting && retryCount < MAX_RETRIES) {
            isReconnecting = true;
            websocketExecutor.submit(this::reconnectWithRetry);
        }
    }

    @Override
    public void onError(Exception arg0) {
        isConnected = false;
        connectionLatch.countDown();
        LOGGER.error("model websocket error", arg0);
    }

    @Override
    public void onMessage(String message) {
        websocketExecutor.submit(() -> {
            try {
                JSONObject json = JSON.parseObject(message);
                modelMessageHandler.handleModelPayload(json);
            } catch (Exception e) {
                LOGGER.error("failed to handle model websocket payload: {}", e.getMessage(), e);
            }
        });
    }

    private void reconnectWithRetry() {
        try {
            while (retryCount < MAX_RETRIES) {
                retryCount++;
                long temp = 1000L * (retryCount - 1) + INITIAL_RECONNECT_DELAY_MS;
                Thread.sleep(Math.min(temp, MAX_RECONNECT_DELAY_MS));
                connectionLatch = new CountDownLatch(1);
                reconnect();
                connectionLatch.await();
                if (isConnected) {
                    LOGGER.info("model websocket reconnected");
                    return;
                }
                LOGGER.warn("model websocket reconnect failed, retry={}", retryCount);
            }
        } catch (InterruptedException e) {
            LOGGER.warn("model websocket reconnect interrupted", e);
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            LOGGER.warn("model websocket reconnect failed, retry={}, message={}", retryCount, e.getMessage(), e);
        } finally {
            isReconnecting = false;
        }
        LOGGER.error("model websocket reconnect exhausted, maxRetries={}", MAX_RETRIES);
    }

    private SSLContext createIgnoreVerifySSL() throws NoSuchAlgorithmException, KeyManagementException {
        SSLContext sc = SSLContext.getInstance("TLS");
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

    @Override
    public void connect() {
        try {
            isConnected = false;
            if (getURI().getScheme().equals("wss")) {
                SSLContext sslContext = createIgnoreVerifySSL();
                SSLSocketFactory factory = sslContext.getSocketFactory();
                this.setSocket(factory.createSocket());
            }
            super.connect();
        } catch (Exception e) {
            LOGGER.error("failed to connect model websocket", e);
        }
    }

    public boolean isConnected() {
        return isConnected && isOpen();
    }
}
