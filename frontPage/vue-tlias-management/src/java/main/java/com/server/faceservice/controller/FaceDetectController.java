package com.server.faceservice.controller;

import com.server.common.utils.R;
import com.server.faceservice.service.FaceDetectService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.InputStream;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CompletableFuture;


@RestController
@RequestMapping("faceDetectService")
public class FaceDetectController {
//    接受前端上传的文件
    @Autowired
    private FaceDetectService faceDetectService;
    // 定义常见的视频文件扩展名（可根据业务需求扩展）
    // 允许的视频MIME类型（与前端beforeUploadVideo中的类型一一对应）
    private Set<String> allowedVideoMimeTypes = new HashSet<>(Arrays.asList(
            "video/mp4",
            "video/ogg",
            "video/flv",
            "video/avi",
            "video/wmv",
            "video/rmvb"
    ));
    // 允许的视频文件后缀（兜底校验，防止MIME类型被篡改）
    private Set<String> allowedVideoSuffixes = new HashSet<>(Arrays.asList(
            "mp4", "ogg", "flv", "avi", "wmv", "rmvb"
    ));

    @PostMapping("/video_upload")
    public R videoUpload(@RequestPart("file") MultipartFile fileUpload, @RequestParam("userId") String userId) {
        if (fileUpload.isEmpty()) {
            // 文件为空
            return R.fail("File is empty");
        }
        String contentType = fileUpload.getContentType();
        boolean isMimeTypeValid = contentType != null && allowedVideoMimeTypes.contains(contentType);
        if (!isMimeTypeValid) {
            String originalFilename = fileUpload.getOriginalFilename();
            // 文件名为空直接判定不合法
            if (originalFilename == null || !originalFilename.contains(".")) {
                return R.fail("上传文件类型不合法，请上传视频文件");
            }
            // 提取后缀并转小写（兼容大小写后缀，如.MP4/.Mp4）
            String suffix = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();
            if (!allowedVideoSuffixes.contains(suffix)) {
                return R.fail("上传文件类型不合法，请上传视频文件");
            }
        }
        if (!faceDetectService.isConnected()){
            return R.fail("上传失败！模型端连接出错");
        }

            try {
//                处理文件
                InputStream inputStream = fileUpload.getInputStream();
//                faceDetectService.processVideo(inputStream, userId);
            } catch (Exception e) {
                e.printStackTrace();
                return R.fail("文件上传处理失败：" + e.getMessage());
            }

        return R.ok("文件上传成功");
    }
}
