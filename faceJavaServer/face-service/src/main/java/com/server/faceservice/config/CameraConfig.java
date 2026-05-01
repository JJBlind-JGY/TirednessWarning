package com.server.faceservice.config;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CameraConfig {
    private String id;
    private String name;
    private String rtspUrl;

    public CameraConfig() {
    }

    public CameraConfig(String id, String name, String rtspUrl) {
        this.id = id;
        this.name = name;
        this.rtspUrl = rtspUrl;
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getRtspUrl() {
        return rtspUrl;
    }

    public void setRtspUrl(String rtspUrl) {
        this.rtspUrl = rtspUrl;
    }

}
