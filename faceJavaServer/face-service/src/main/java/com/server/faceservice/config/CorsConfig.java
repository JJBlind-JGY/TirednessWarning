package com.server.faceservice.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class CorsConfig {
    @Value("${web.url}")
    private String web_url;
    @Bean
    public WebMvcConfigurer corsConfigurer() {
//        跨域配置，允许前端访问服务器
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                registry.addMapping("/**") // 允许所有路径
                        .allowedOriginPatterns(web_url) // 允许的来源
                        .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS") // 允许的方法
                        .allowedHeaders("*") // 允许的头
                        .allowCredentials(true) // 允许凭证
                        .maxAge(3600); // 预检请求的缓存时间
            }
        };
    }
}