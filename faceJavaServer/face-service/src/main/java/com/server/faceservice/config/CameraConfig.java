package com.server.faceservice.config;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonIgnore;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CameraConfig {
    private String id;
    private String name;
    private String sourceType;
    private Integer deviceIndex;
    private String rtspUrl;
    private String streamName;

    public CameraConfig() {
    }

    public CameraConfig(String id, String name, String rtspUrl) {
        this(id, name, rtspUrl, id);
    }

    public CameraConfig(String id, String name, String rtspUrl, String streamName) {
        this(id, name, "rtsp", 0, rtspUrl, streamName);
    }

    public CameraConfig(String id, String name, String sourceType, Integer deviceIndex, String rtspUrl, String streamName) {
        this.id = id;
        this.name = name;
        this.sourceType = sourceType;
        this.deviceIndex = deviceIndex;
        this.rtspUrl = rtspUrl;
        this.streamName = streamName;
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

    public String getSourceType() {
        return sourceType;
    }

    public void setSourceType(String sourceType) {
        this.sourceType = sourceType;
    }

    public Integer getDeviceIndex() {
        return deviceIndex;
    }

    public void setDeviceIndex(Integer deviceIndex) {
        this.deviceIndex = deviceIndex;
    }

    public String getRtspUrl() {
        return rtspUrl;
    }

    public void setRtspUrl(String rtspUrl) {
        this.rtspUrl = rtspUrl;
    }

    public String getStreamName() {
        return streamName;
    }

    public void setStreamName(String streamName) {
        this.streamName = streamName;
    }

    @JsonIgnore
    public boolean isLocal() {
        return "local".equalsIgnoreCase(sourceType);
    }
}
