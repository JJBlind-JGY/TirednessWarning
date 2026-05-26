package com.server.faceservice.controller;

import com.server.common.utils.R;
import com.server.faceservice.config.AbnormalSampleRequest;
import com.server.faceservice.config.AlertLog;
import com.server.faceservice.config.CameraConfig;
import com.server.faceservice.config.NormalInferenceLog;
import com.server.faceservice.config.PersonnelConfig;
import com.server.faceservice.config.VideoStreamAutoRunner;
import com.server.faceservice.service.AbnormalSampleService;
import com.server.faceservice.service.AlertLogService;
import com.server.faceservice.service.CameraConfigService;
import com.server.faceservice.service.FaceDetectService;
import com.server.faceservice.service.NormalInferenceLogService;
import com.server.faceservice.service.PersonnelConfigService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.InputStream;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("faceDetectService")
public class FaceDetectController {
    @Autowired
    private FaceDetectService faceDetectService;

    @Autowired
    private CameraConfigService cameraConfigService;

    @Autowired
    private PersonnelConfigService personnelConfigService;

    @Autowired
    private AlertLogService alertLogService;

    @Autowired
    private NormalInferenceLogService normalInferenceLogService;

    @Autowired
    private AbnormalSampleService abnormalSampleService;

    @Autowired
    private VideoStreamAutoRunner videoStreamAutoRunner;

    private final Set<String> allowedVideoMimeTypes = new HashSet<>(Arrays.asList(
            "video/mp4",
            "video/ogg",
            "video/flv",
            "video/avi",
            "video/wmv",
            "video/rmvb"
    ));

    private final Set<String> allowedVideoSuffixes = new HashSet<>(Arrays.asList(
            "mp4", "ogg", "flv", "avi", "wmv", "rmvb"
    ));

    @PostMapping("/video_upload")
    public R videoUpload(@RequestPart("file") MultipartFile fileUpload, @RequestParam("userId") String userId) {
        if (fileUpload.isEmpty()) {
            return R.fail("File is empty");
        }

        String contentType = fileUpload.getContentType();
        boolean isMimeTypeValid = contentType != null && allowedVideoMimeTypes.contains(contentType);
        if (!isMimeTypeValid) {
            String originalFilename = fileUpload.getOriginalFilename();
            if (originalFilename == null || !originalFilename.contains(".")) {
                return R.fail("Invalid video file type");
            }
            String suffix = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();
            if (!allowedVideoSuffixes.contains(suffix)) {
                return R.fail("Invalid video file type");
            }
        }

        if (!faceDetectService.isConnected()) {
            return R.fail("Model service is not connected");
        }

        try {
            InputStream inputStream = fileUpload.getInputStream();
            inputStream.close();
        } catch (Exception e) {
            return R.fail("Video upload failed: " + e.getMessage());
        }

        return R.ok("Video uploaded");
    }

    @GetMapping("/cameras")
    public R listCameras() {
        return R.ok(Map.of("data", cameraConfigService.list()));
    }

    @GetMapping("/cameras/status")
    public R listCameraStatuses() {
        return R.ok(Map.of("data", videoStreamAutoRunner.getCameraStatuses()));
    }

    @PostMapping("/cameras")
    public R saveCamera(@RequestBody CameraConfig camera) {
        try {
            CameraConfig saved = cameraConfigService.upsert(camera);
            videoStreamAutoRunner.reloadStreams();
            return R.ok(Map.of("data", saved));
        } catch (IllegalArgumentException e) {
            return R.fail(e.getMessage());
        }
    }

    @DeleteMapping("/cameras/{cameraId}")
    public R removeCamera(@PathVariable String cameraId) {
        boolean removed = cameraConfigService.remove(cameraId);
        videoStreamAutoRunner.reloadStreams();
        return removed ? R.ok() : R.fail("Camera not found");
    }

    @GetMapping("/personnel")
    public R listPersonnel() {
        return R.ok(Map.of("data", personnelConfigService.list()));
    }

    @PostMapping("/personnel")
    public R savePersonnel(@RequestBody PersonnelConfig personnel) {
        try {
            PersonnelConfig saved = personnelConfigService.upsert(personnel);
            return R.ok(Map.of("data", saved));
        } catch (IllegalArgumentException e) {
            return R.fail(e.getMessage());
        }
    }

    @DeleteMapping("/personnel/{personnelId}")
    public R removePersonnel(@PathVariable String personnelId) {
        boolean removed = personnelConfigService.remove(personnelId);
        return removed ? R.ok() : R.fail("Personnel not found");
    }

    @GetMapping("/alert-logs/today")
    public R listTodayAlertLogs() {
        return R.ok(Map.of("data", alertLogService.listToday()));
    }

    @GetMapping("/alert-logs")
    public R listAlertLogs(@RequestParam String date) {
        try {
            return R.ok(Map.of("data", alertLogService.list(date)));
        } catch (IllegalArgumentException e) {
            return R.fail(e.getMessage());
        }
    }

    @PostMapping("/alert-logs")
    public R appendAlertLog(@RequestBody AlertLog alertLog) {
        try {
            return R.ok(Map.of("data", alertLogService.append(alertLog)));
        } catch (IllegalArgumentException e) {
            return R.fail(e.getMessage());
        }
    }

    @PostMapping("/normal-inference-logs")
    public R appendNormalInferenceLog(@RequestBody NormalInferenceLog normalInferenceLog) {
        return R.ok(Map.of("data", normalInferenceLogService.append(normalInferenceLog)));
    }

    @PostMapping("/abnormal-samples")
    public R captureAbnormalSample(@RequestBody AbnormalSampleRequest request) {
        return R.ok(Map.of("data", abnormalSampleService.capture(request)));
    }
}
