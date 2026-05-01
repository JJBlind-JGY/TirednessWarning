package com.server.faceservice.config;

import com.server.faceservice.utils.ModelMessageHandler;
import com.server.faceservice.utils.ModelWebsocket;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;

import java.net.URI;
import java.net.URISyntaxException;

@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer{
//    Websocket配置，配置消息推送路径+跨域配置
    @Value("${web.url}")
    private String web_url;
    @Value("${websocket.modelServer.url}")
    private String modelWebsocketUrl;
    @Bean
    public ModelWebsocket modelWebsocket() throws Exception {
        return new ModelWebsocket(new URI(modelWebsocketUrl));
    }
    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        registry.enableSimpleBroker("/topic", "/queue");
        registry.setApplicationDestinationPrefixes("/app"); // 后端处理的消息前缀
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.addEndpoint("/wss").setAllowedOriginPatterns(web_url).withSockJS();
    }

}