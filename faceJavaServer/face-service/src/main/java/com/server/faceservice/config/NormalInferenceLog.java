package com.server.faceservice.config;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.Map;

@JsonIgnoreProperties(ignoreUnknown = true)
public class NormalInferenceLog {
    private String id;
    private String date;
    private long timestamp;
    private String personId;
    private String personName;
    private Integer workerId;
    private String cameraId;
    private String fusionEmotion;
    private String faceEmotion;
    private String eegEmotion;
    private int confidence;
    private Map<String, Integer> sampleCounts;
    private String message;

    public NormalInferenceLog() {
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getDate() {
        return date;
    }

    public void setDate(String date) {
        this.date = date;
    }

    public long getTimestamp() {
        return timestamp;
    }

    public void setTimestamp(long timestamp) {
        this.timestamp = timestamp;
    }

    public String getPersonId() {
        return personId;
    }

    public void setPersonId(String personId) {
        this.personId = personId;
    }

    public String getPersonName() {
        return personName;
    }

    public void setPersonName(String personName) {
        this.personName = personName;
    }

    public Integer getWorkerId() {
        return workerId;
    }

    public void setWorkerId(Integer workerId) {
        this.workerId = workerId;
    }

    public String getCameraId() {
        return cameraId;
    }

    public void setCameraId(String cameraId) {
        this.cameraId = cameraId;
    }

    public String getFusionEmotion() {
        return fusionEmotion;
    }

    public void setFusionEmotion(String fusionEmotion) {
        this.fusionEmotion = fusionEmotion;
    }

    public String getFaceEmotion() {
        return faceEmotion;
    }

    public void setFaceEmotion(String faceEmotion) {
        this.faceEmotion = faceEmotion;
    }

    public String getEegEmotion() {
        return eegEmotion;
    }

    public void setEegEmotion(String eegEmotion) {
        this.eegEmotion = eegEmotion;
    }

    public int getConfidence() {
        return confidence;
    }

    public void setConfidence(int confidence) {
        this.confidence = confidence;
    }

    public Map<String, Integer> getSampleCounts() {
        return sampleCounts;
    }

    public void setSampleCounts(Map<String, Integer> sampleCounts) {
        this.sampleCounts = sampleCounts;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }
}
