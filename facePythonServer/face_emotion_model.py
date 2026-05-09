# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import cv2
import numpy as np


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_DIR = os.environ.get("FACE_MODEL_DIR", os.path.join(BASE_DIR, "models"))
DEFAULT_YUNET_MODEL = os.path.join(DEFAULT_MODEL_DIR, "face_detection_yunet_2023mar.onnx")
DEFAULT_EMOTION_MODEL = os.path.join(DEFAULT_MODEL_DIR, "enet_b2_7.onnx")
DEFAULT_EYE_MODEL = os.path.join(DEFAULT_MODEL_DIR, "open-closed-eye.onnx")

EMOTION7_LABELS = ["Anger", "Disgust", "Fear", "Happiness", "Neutral", "Sadness", "Surprise"]
EMOTION7_TO_5 = {
    "Anger": ("fatigue", "疲劳", 1),
    "Disgust": ("stress", "紧张", 2),
    "Fear": ("anxiety", "焦虑", 3),
    "Happiness": ("normal", "其他", 4),
    "Neutral": ("normal", "其他", 4),
    "Sadness": ("weakness", "虚弱", 0),
    "Surprise": ("normal", "其他", 4),
}

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass
class FaceEmotionResult:
    status: str
    emotion_id: int
    emotion5: str
    emotion5_zh: str
    emotion7: str
    score: float
    fatigue_index: float
    fatigue_rank: int
    face_box: list | None
    scores7: dict
    image_bytes: bytes | None
    eye_status: str
    eye_closed: bool | None
    eye_closed_score: float
    eye_open_score: float
    eye_boxes: list


class YuNetEmotiEffRecognizer:
    def __init__(
        self,
        yunet_model=DEFAULT_YUNET_MODEL,
        emotion_model=DEFAULT_EMOTION_MODEL,
        eye_model=DEFAULT_EYE_MODEL,
        input_size=260,
        face_score_threshold=0.7,
        eye_closed_threshold=0.65,
    ):
        self.yunet_model = yunet_model
        self.emotion_model = emotion_model
        self.eye_model = eye_model
        self.input_size = input_size
        self.eye_closed_threshold = eye_closed_threshold
        self.lock = threading.Lock()

        if not os.path.exists(self.yunet_model):
            raise FileNotFoundError(f"YuNet model not found: {self.yunet_model}")
        if not os.path.exists(self.emotion_model):
            raise FileNotFoundError(f"EmotiEff model not found: {self.emotion_model}")
        if not os.path.exists(self.eye_model):
            raise FileNotFoundError(f"Eye open/closed model not found: {self.eye_model}")

        self.detector = cv2.FaceDetectorYN.create(
            self.yunet_model,
            "",
            (320, 320),
            face_score_threshold,
            0.3,
            5000,
        )
        self.emotion_net = cv2.dnn.readNetFromONNX(self.emotion_model)
        self.eye_net = cv2.dnn.readNetFromONNX(self.eye_model)

    def predict_from_bytes(self, frame_data, draw=True, output_format=".jpg"):
        image = self._decode_image(frame_data)
        if image is None:
            return FaceEmotionResult(
                status="invalid_image",
                emotion_id=4,
                emotion5="normal",
                emotion5_zh="其他",
                emotion7="Unknown",
                score=0.0,
                fatigue_index=0.0,
                fatigue_rank=0,
                face_box=None,
                scores7={},
                image_bytes=None,
                eye_status="invalid",
                eye_closed=None,
                eye_closed_score=0.0,
                eye_open_score=0.0,
                eye_boxes=[],
            )

        face = self._detect_largest_face(image)
        if face is None:
            image_bytes = self._encode_image(image, output_format) if draw else None
            return FaceEmotionResult(
                status="no_face",
                emotion_id=4,
                emotion5="normal",
                emotion5_zh="其他",
                emotion7="Unknown",
                score=0.0,
                fatigue_index=0.0,
                fatigue_rank=0,
                face_box=None,
                scores7={},
                image_bytes=image_bytes,
                eye_status="no_face",
                eye_closed=None,
                eye_closed_score=0.0,
                eye_open_score=0.0,
                eye_boxes=[],
            )

        face_box = face["box"]
        landmarks = face["landmarks"]
        face_crop = self._crop_face(image, face_box)
        logits = self._predict_logits(face_crop)
        probs = self._softmax(logits)
        top_index = int(np.argmax(probs))
        emotion7 = EMOTION7_LABELS[top_index]
        emotion5, emotion5_zh, emotion_id = EMOTION7_TO_5[emotion7]
        confidence = float(probs[top_index])
        fatigue_index = self._build_fatigue_index(emotion5, confidence)
        fatigue_rank = self._build_fatigue_rank(fatigue_index)
        eye_result = self._predict_eye_state(image, face_box, landmarks)

        if draw:
            self._draw_result(image, face_box, f"{emotion5_zh} {confidence * 100:.1f}%")
            self._draw_eye_result(image, eye_result)
        image_bytes = self._encode_image(image, output_format) if draw else None

        return FaceEmotionResult(
            status="ok",
            emotion_id=emotion_id,
            emotion5=emotion5,
            emotion5_zh=emotion5_zh,
            emotion7=emotion7,
            score=confidence * 100,
            fatigue_index=fatigue_index,
            fatigue_rank=fatigue_rank,
            face_box=face_box,
            scores7={label: float(probs[index]) for index, label in enumerate(EMOTION7_LABELS)},
            image_bytes=image_bytes,
            eye_status=eye_result["status"],
            eye_closed=eye_result["closed"],
            eye_closed_score=eye_result["closed_score"],
            eye_open_score=eye_result["open_score"],
            eye_boxes=eye_result["boxes"],
        )

    def _decode_image(self, frame_data):
        arr = np.frombuffer(frame_data, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def _detect_largest_face(self, image):
        h, w = image.shape[:2]
        with self.lock:
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(image)
        if faces is None or len(faces) == 0:
            return None

        best = max(faces, key=lambda face: face[2] * face[3])
        x, y, bw, bh = best[:4]
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(w, int(x + bw))
        y2 = min(h, int(y + bh))
        if x2 <= x1 or y2 <= y1:
            return None
        landmarks = []
        if len(best) >= 14:
            landmarks = [[float(best[i]), float(best[i + 1])] for i in range(4, 14, 2)]
        return {"box": [x1, y1, x2, y2], "landmarks": landmarks}

    def _crop_face(self, image, box, padding_ratio=0.15):
        x1, y1, x2, y2 = box
        h, w = image.shape[:2]
        face_w = x2 - x1
        face_h = y2 - y1
        pad_x = int(face_w * padding_ratio)
        pad_y = int(face_h * padding_ratio)

        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        return image[y1:y2, x1:x2]

    def _predict_logits(self, face_bgr):
        face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(face_rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_AREA)
        image = resized.astype(np.float32) / 255.0
        image = (image - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
        blob = np.transpose(image, (2, 0, 1))[np.newaxis, :, :, :].astype(np.float32)

        with self.lock:
            self.emotion_net.setInput(blob)
            logits = self.emotion_net.forward()
        return logits.reshape(-1)

    def _predict_eye_state(self, image, face_box, landmarks):
        eye_crops = self._crop_eye_regions(image, face_box, landmarks)
        if not eye_crops:
            return {"status": "invalid_eye", "closed": None, "closed_score": 0.0, "open_score": 0.0, "boxes": []}

        open_scores = []
        closed_scores = []
        boxes = []
        for crop, box in eye_crops:
            resized = cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA)
            blob = cv2.dnn.blobFromImage(resized, scalefactor=1.0 / 255.0, size=(32, 32), mean=(127.0, 127.0, 127.0), swapRB=False, crop=False)
            with self.lock:
                self.eye_net.setInput(blob)
                output = self.eye_net.forward().reshape(-1)
            output_sum = float(np.sum(output))
            if np.all(output >= 0) and abs(output_sum - 1.0) <= 0.05:
                probs = output
            else:
                probs = self._softmax(output)
            if len(probs) < 2:
                continue
            open_scores.append(float(probs[0]))
            closed_scores.append(float(probs[1]))
            boxes.append(box)

        if not closed_scores:
            return {"status": "invalid_eye", "closed": None, "closed_score": 0.0, "open_score": 0.0, "boxes": boxes}

        open_score = float(np.mean(open_scores))
        closed_score = float(np.min(closed_scores))
        closed = closed_score >= self.eye_closed_threshold
        return {
            "status": "closed" if closed else "open",
            "closed": bool(closed),
            "closed_score": closed_score,
            "open_score": open_score,
            "boxes": boxes,
        }

    def _crop_eye_regions(self, image, face_box, landmarks):
        x1, y1, x2, y2 = face_box
        face_w = x2 - x1
        face_h = y2 - y1
        if face_w <= 0 or face_h <= 0:
            return []

        if len(landmarks) >= 2:
            centers = landmarks[:2]
        else:
            centers = [
                [x1 + face_w * 0.35, y1 + face_h * 0.38],
                [x1 + face_w * 0.65, y1 + face_h * 0.38],
            ]

        h, w = image.shape[:2]
        side = max(12, int(min(face_w * 0.26, face_h * 0.22)))
        crops = []
        for center_x, center_y in centers:
            cx = int(center_x)
            cy = int(center_y)
            ex1 = max(0, cx - side)
            ey1 = max(0, cy - side)
            ex2 = min(w, cx + side)
            ey2 = min(h, cy + side)
            if ex2 - ex1 < 8 or ey2 - ey1 < 8:
                continue
            crops.append((image[ey1:ey2, ex1:ex2], [ex1, ey1, ex2, ey2]))
        return crops

    def _softmax(self, logits):
        logits = logits - np.max(logits)
        exp = np.exp(logits)
        total = np.sum(exp)
        if total <= 0:
            return np.ones_like(exp) / len(exp)
        return exp / total

    def _build_fatigue_index(self, emotion5, confidence):
        base = {
            "normal": 1.0,
            "anxiety": 5.5,
            "stress": 6.0,
            "fatigue": 7.5,
            "weakness": 7.0,
        }.get(emotion5, 1.0)
        return float(np.clip(base + confidence * 2.0, 0.0, 10.0))

    def _build_fatigue_rank(self, fatigue_index):
        if fatigue_index >= 7.5:
            return 3
        if fatigue_index >= 6.0:
            return 2
        if fatigue_index >= 4.0:
            return 1
        return 0

    def _draw_result(self, image, box, label):
        x1, y1, x2, y2 = box
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 180, 120), 2)
        label_y = max(22, y1 - 8)
        cv2.putText(image, label, (x1, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 120), 2)

    def _draw_eye_result(self, image, eye_result):
        if not eye_result or eye_result.get("closed") is None:
            return
        color = (0, 0, 220) if eye_result["closed"] else (0, 180, 120)
        label = f"eye {eye_result['status']} {eye_result['closed_score'] * 100:.1f}%"
        for box in eye_result.get("boxes", []):
            x1, y1, x2, y2 = box
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 1)
        first_box = eye_result.get("boxes", [[8, 22, 0, 0]])[0]
        cv2.putText(image, label, (first_box[0], max(18, first_box[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    def _encode_image(self, image, output_format):
        success, encoded = cv2.imencode(output_format, image)
        if not success:
            return None
        return encoded.tobytes()
