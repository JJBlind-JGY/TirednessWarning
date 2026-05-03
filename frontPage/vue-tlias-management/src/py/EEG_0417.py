# -*- coding: utf-8 -*-
"""
简化版 Flask + SSE 脑电服务。

保留内容：
- TGAM 协议解析
- 脑电特征提取
- 情绪分析

调整内容：
- 同一 worker 只保留最新一条 SSE 流
- 不再使用信号质量阻断前端输出
- 修正中文返回字段
"""

import json
import logging
import os
import queue
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime

import numpy as np
import serial
from flask import Flask, Response, request
from scipy.signal import butter, lfilter, lfilter_zi
from scipy.special import softmax


app = Flask(__name__)

logger = logging.getLogger("emotion")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler("emotion_access.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)
logger.propagate = False


MAX_WORKERS = 8
DEFAULT_WORKER_ID = 1
DEFAULT_PORT = ""
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get("EEG_CONFIG_FILE", os.path.join(BASE_DIR, "config", "eeg-devices.json"))
BAUDRATE = 57600

RAW_FS = 512
TARGET_FS = 128
SAMPLE_SEC = 4
WINDOW_SIZE = RAW_FS * SAMPLE_SEC
DOWNSAMPLE_FACTOR = RAW_FS // TARGET_FS
BP_B, BP_A = butter(4, [1 / (RAW_FS / 2), 40 / (RAW_FS / 2)], btype="band")
BASELINE_SEC = 30
MIN_BASELINE_SAMPLES = 10
NO_CONTACT_SIGNAL_VALUE = 200
POOR_SIGNAL_THRESHOLD = 100
STRONG_BAD_CONTACT_SIGNAL_VALUES = {107}
WEAK_CONTACT_SIGNAL_VALUES = {29, 54, 55, 56, 80, 81, 82}
BAD_CONTACT_SIGNAL_VALUES = STRONG_BAD_CONTACT_SIGNAL_VALUES | WEAK_CONTACT_SIGNAL_VALUES
BLOCKING_SIGNAL_VALUES = STRONG_BAD_CONTACT_SIGNAL_VALUES | {NO_CONTACT_SIGNAL_VALUE}
BASELINE_MAX_SAMPLES = 180

PARSER_SYNC = 0xAA
PARSER_EXCODE = 0x55
PARSER_CODE_POOR_SIGNAL = 0x02
PARSER_CODE_ATTENTION = 0x04
PARSER_CODE_MEDITATION = 0x05
PARSER_CODE_RAW = 0x80
PARSER_CODE_EEG_POWER = 0x83


class TGAMParser:
    STATE_SYNC, STATE_SYNC2, STATE_LEN, STATE_PAYLOAD, STATE_CHK = 1, 2, 3, 4, 5

    def __init__(self):
        self.state = self.STATE_SYNC
        self.payload_len = 0
        self.payload = bytearray()
        self.payload_sum = 0

    def feed(self, byte_stream):
        events = []
        for b in byte_stream:
            b &= 0xFF
            if self.state == self.STATE_SYNC:
                if b == PARSER_SYNC:
                    self.state = self.STATE_SYNC2
            elif self.state == self.STATE_SYNC2:
                self.state = self.STATE_LEN if b == PARSER_SYNC else self.STATE_SYNC
            elif self.state == self.STATE_LEN:
                if b > 169:
                    self.state = self.STATE_SYNC
                else:
                    self.payload_len = b
                    self.payload = bytearray()
                    self.payload_sum = 0
                    self.state = self.STATE_PAYLOAD
            elif self.state == self.STATE_PAYLOAD:
                self.payload.append(b)
                self.payload_sum = (self.payload_sum + b) & 0xFF
                if len(self.payload) >= self.payload_len:
                    self.state = self.STATE_CHK
            elif self.state == self.STATE_CHK:
                expected = (~self.payload_sum) & 0xFF
                if b == expected:
                    events.extend(self._parse_payload())
                self.state = self.STATE_SYNC
        return events

    def _parse_payload(self):
        out = []
        i = 0
        payload = self.payload

        while i < len(payload):
            while i < len(payload) and payload[i] == PARSER_EXCODE:
                i += 1
            if i >= len(payload):
                break

            code = payload[i]
            i += 1

            if code >= 0x80:
                if i >= len(payload):
                    break
                value_len = payload[i]
                i += 1
            else:
                value_len = 1

            if i + value_len > len(payload):
                break

            value_bytes = payload[i : i + value_len]
            i += value_len

            if code == PARSER_CODE_RAW and value_len == 2:
                value = (value_bytes[0] << 8) | value_bytes[1]
                if value >= 32768:
                    value -= 65536
                out.append({"type": "raw", "value": value})
            elif code == PARSER_CODE_POOR_SIGNAL:
                out.append({"type": "signal", "value": value_bytes[0]})
            elif code == PARSER_CODE_ATTENTION:
                out.append({"type": "attention", "value": value_bytes[0]})
            elif code == PARSER_CODE_MEDITATION:
                out.append({"type": "meditation", "value": value_bytes[0]})
            elif code == PARSER_CODE_EEG_POWER and value_len == 24:
                powers = []
                for index in range(8):
                    hi = value_bytes[index * 3]
                    mid = value_bytes[index * 3 + 1]
                    lo = value_bytes[index * 3 + 2]
                    powers.append((hi << 16) | (mid << 8) | lo)
                out.append(
                    {
                        "type": "eeg_power",
                        "value": {
                            "delta": powers[0],
                            "theta": powers[1],
                            "low_alpha": powers[2],
                            "high_alpha": powers[3],
                            "low_beta": powers[4],
                            "high_beta": powers[5],
                            "low_gamma": powers[6],
                            "mid_gamma": powers[7],
                        },
                    }
                )
        return out


class EmotionAnalyzer:
    EMOTION_WEIGHTS = {
        "anxiety": np.array([-0.3, -0.6, -0.2, 1.5, -0.2, 1.0, -0.8, 0.3]),
        "stress": np.array([-0.5, -1.2, -1.0, 0.5, -0.4, 1.2, -0.6, 0.4]),
        "fatigue": np.array([1.3, 0.3, 1.5, -0.3, 0.4, -0.8, 1.0, 0.0]),
        "weakness": np.array([0.6, 0.2, 0.8, -0.4, 1.4, -1.0, 0.2, -1.0]),
    }
    EMOTION_NAMES_ZH = {
        "normal": "正常",
        "anxiety": "焦虑",
        "stress": "紧张",
        "fatigue": "疲劳",
        "weakness": "虚弱",
    }

    def __init__(self, baseline_sec=BASELINE_SEC):
        self.baseline_sec = baseline_sec
        self.start_time = time.time()
        self.baseline_features = []
        self.baseline_mean = None
        self.baseline_std = None
        self.smoothed_probs = None
        self.ema_alpha = 0.18
        self.last_emotion = "normal"
        self.hold_counter = 0
        self.HOLD_THRESHOLD = 6
        self.NORMAL_BIAS = 0.35
        self.MIN_ALERT_PROB = 0.62
        self.MIN_ALERT_SCORE = 0.75
        self.SWITCH_MARGIN = 0.15

    def _extract_features(self, eeg_power):
        eps = 1e-8
        delta = eeg_power["delta"]
        theta = eeg_power["theta"]
        alpha = eeg_power["low_alpha"] + eeg_power["high_alpha"]
        beta = eeg_power["low_beta"] + eeg_power["high_beta"]
        beta_high = eeg_power["high_beta"]
        gamma = eeg_power["low_gamma"] + eeg_power["mid_gamma"]
        total = delta + theta + alpha + beta + gamma + eps

        return np.array(
            [
                theta / (beta + eps),
                alpha / (beta + eps),
                (theta + alpha) / (beta + eps),
                beta_high / (alpha + eps),
                (delta + theta) / total,
                beta / total,
                alpha / total,
                np.log1p(total),
            ],
            dtype=np.float64,
        )

    def _zscore(self, feats):
        if self.baseline_mean is None:
            return feats
        return (feats - self.baseline_mean) / (self.baseline_std + 1e-6)

    def is_baseline_ready(self):
        return self.baseline_mean is not None

    def _build_baseline(self):
        arr = np.array(self.baseline_features)
        self.baseline_mean = np.mean(arr, axis=0)
        self.baseline_std = np.std(arr, axis=0) + 1e-6
        logger.info("baseline ready | mean=%s", self.baseline_mean.round(3).tolist())

    def analyze(self, eeg_power, signal_quality):
        feats = self._extract_features(eeg_power)
        elapsed = time.time() - self.start_time

        if not self.is_baseline_ready():
            self.baseline_features.append(feats)
            if elapsed >= self.baseline_sec and len(self.baseline_features) >= 10:
                self._build_baseline()
            return {
                "status": "calibrating",
                "calibration_progress": min(1.0, elapsed / self.baseline_sec),
                "signal_quality": 0,
                "emotion": "normal",
                "emotion_zh": "基线校准中",
                "probs": {},
                "features": feats.tolist(),
            }

        z = np.clip(self._zscore(feats), -2.5, 2.5)
        scores = {"normal": self.NORMAL_BIAS}
        for name, weight in self.EMOTION_WEIGHTS.items():
            scores[name] = float(np.dot(weight, z))

        names = list(scores.keys())
        logits = np.array([scores[name] for name in names])
        probs = softmax(logits)

        if self.smoothed_probs is None:
            self.smoothed_probs = probs
        else:
            self.smoothed_probs = self.ema_alpha * probs + (1 - self.ema_alpha) * self.smoothed_probs

        top_idx = int(np.argmax(self.smoothed_probs))
        top_name = names[top_idx]
        top_prob = float(self.smoothed_probs[top_idx])
        top_score = float(scores[top_name])
        sorted_probs = np.sort(self.smoothed_probs)
        second_prob = float(sorted_probs[-2]) if len(sorted_probs) > 1 else 0.0

        if (
            top_name == "normal"
            or top_prob < self.MIN_ALERT_PROB
            or top_score < self.MIN_ALERT_SCORE
            or (top_prob - second_prob) < self.SWITCH_MARGIN
        ):
            candidate = "normal"
        else:
            candidate = top_name

        if candidate == self.last_emotion:
            self.hold_counter = 0
        else:
            self.hold_counter += 1
            required_hold = 2 if candidate == "normal" else self.HOLD_THRESHOLD
            if self.hold_counter >= required_hold:
                self.last_emotion = candidate
                self.hold_counter = 0
            else:
                candidate = self.last_emotion

        prob_dict = {name: float(prob) for name, prob in zip(names, self.smoothed_probs)}
        raw_indices = {
            "anxiety_idx": float(np.clip(scores["anxiety"] * 20 + 50, 0, 100)),
            "stress_idx": float(np.clip(scores["stress"] * 20 + 50, 0, 100)),
            "fatigue_idx": float(np.clip(scores["fatigue"] * 20 + 50, 0, 100)),
            "weakness_idx": float(np.clip(scores["weakness"] * 20 + 50, 0, 100)),
        }

        return {
            "status": "ok",
            "signal_quality": 0,
            "emotion": candidate,
            "emotion_zh": self.EMOTION_NAMES_ZH[candidate],
            "probs": prob_dict,
            "indices": raw_indices,
            "features": feats.tolist(),
        }


class EEGAnalyzer:
    EMOTION_NAMES_ZH = {
        "normal": "正常",
        "anxiety": "焦虑",
        "stress": "紧张",
        "fatigue": "疲劳",
        "weakness": "虚弱",
    }
    STATUS_NAMES_ZH = {
        "calibrating": "基线校准中",
        "no_contact": "等待佩戴",
        "poor_signal": "信号质量不佳",
    }
    FEATURE_NAMES = (
        "theta_alpha",
        "theta_beta",
        "theta_alpha_beta",
        "engagement",
        "alpha_beta",
        "slow_ratio",
        "beta_ratio",
        "gamma_ratio",
    )

    def __init__(self, baseline_sec=BASELINE_SEC):
        self.baseline_sec = baseline_sec
        self.start_time = time.time()
        self.baseline_features = deque(maxlen=BASELINE_MAX_SAMPLES)
        self.baseline_mean = None
        self.baseline_std = None
        self.smoothed_indices = None
        self.last_emotion = "normal"
        self.pending_emotion = "normal"
        self.hold_counter = 0
        self.ema_alpha = 0.32
        self.normal_baseline_alpha = 0.03
        self.mild_baseline_alpha = 0.008
        self.index_history = deque(maxlen=8)

    def _quality_level(self, signal_quality):
        if signal_quality is None:
            return "unknown"
        if signal_quality == NO_CONTACT_SIGNAL_VALUE:
            return "no_contact"
        if signal_quality in STRONG_BAD_CONTACT_SIGNAL_VALUES:
            return "bad_contact"
        if signal_quality == 0:
            return "good"
        if signal_quality < 25:
            return "fair"
        if signal_quality < 50:
            return "usable"
        if signal_quality < POOR_SIGNAL_THRESHOLD:
            return "noisy"
        return "poor"

    def _is_signal_clean(self, signal_quality):
        return self._quality_level(signal_quality) in {"good", "fair", "usable", "noisy"}

    def _extract_features(self, eeg_power):
        eps = 1e-8
        delta = float(eeg_power["delta"])
        theta = float(eeg_power["theta"])
        alpha = float(eeg_power["low_alpha"]) + float(eeg_power["high_alpha"])
        beta = float(eeg_power["low_beta"]) + float(eeg_power["high_beta"])
        gamma = float(eeg_power["low_gamma"]) + float(eeg_power["mid_gamma"])
        total = delta + theta + alpha + beta + gamma + eps

        values = np.array(
            [
                theta / (alpha + eps),
                theta / (beta + eps),
                (theta + alpha) / (beta + eps),
                beta / (alpha + theta + eps),
                alpha / (beta + eps),
                (delta + theta) / total,
                beta / total,
                gamma / total,
            ],
            dtype=np.float64,
        )
        return np.nan_to_num(values, nan=0.0, posinf=100.0, neginf=0.0)

    def _feature_dict(self, feats, z=None):
        out = {name: float(value) for name, value in zip(self.FEATURE_NAMES, feats)}
        if z is not None:
            out["z"] = {name: float(value) for name, value in zip(self.FEATURE_NAMES, z)}
        return out

    def _empty_indices(self):
        return {"anxiety_idx": 0.0, "stress_idx": 0.0, "fatigue_idx": 0.0, "weakness_idx": 0.0}

    def _reset_current_prediction(self):
        self.last_emotion = "normal"
        self.pending_emotion = "normal"
        self.hold_counter = 0

    def _invalid_result(self, status, signal_quality, quality_level, attention, meditation, feats, reason_codes):
        self._reset_current_prediction()
        return {
            "status": status,
            "valid_current": False,
            "model_type": "rule_based_eeg_state_estimation",
            "calibration_progress": 1.0 if self.is_baseline_ready() else 0.0,
            "signal_quality": signal_quality,
            "quality_level": quality_level,
            "attention": attention,
            "meditation": meditation,
            "emotion": "normal",
            "emotion_zh": self.STATUS_NAMES_ZH.get(status, self.EMOTION_NAMES_ZH["normal"]),
            "probs": {},
            "indices": self._empty_indices(),
            "features": self._feature_dict(feats),
            "baseline_warning": "",
            "reason_codes": reason_codes,
        }

    def _baseline_warning(self, feats, indices=None):
        theta_beta = float(feats[1])
        slow_ratio = float(feats[5])
        if indices and (indices.get("fatigue_idx", 0) >= 62 or indices.get("weakness_idx", 0) >= 62):
            return "initial_state_may_not_be_normal"
        if theta_beta >= 2.8 or slow_ratio >= 0.72:
            return "initial_state_may_not_be_normal"
        return ""

    def _build_baseline(self):
        arr = np.array(self.baseline_features, dtype=np.float64)
        self.baseline_mean = np.mean(arr, axis=0)
        self.baseline_std = np.maximum(np.std(arr, axis=0), 0.04)
        logger.info("eeg baseline ready | mean=%s", self.baseline_mean.round(3).tolist())

    def _zscore(self, feats):
        if self.baseline_mean is None:
            return np.zeros_like(feats)
        return np.clip((feats - self.baseline_mean) / (self.baseline_std + 1e-6), -3.5, 3.5)

    def is_baseline_ready(self):
        return self.baseline_mean is not None

    def _scale_score(self, weighted_z, base=50.0, gain=13.5):
        return float(np.clip(base + gain * weighted_z, 0.0, 100.0))

    def _build_indices(self, z):
        theta_alpha, theta_beta, theta_alpha_beta, engagement, alpha_beta, slow_ratio, beta_ratio, gamma_ratio = z
        indices = {
            "fatigue_idx": self._scale_score(
                0.30 * theta_alpha
                + 0.30 * theta_beta
                + 0.22 * theta_alpha_beta
                + 0.24 * slow_ratio
                - 0.20 * engagement
                - 0.14 * beta_ratio
            ),
            "stress_idx": self._scale_score(
                0.36 * beta_ratio
                + 0.28 * engagement
                + 0.20 * gamma_ratio
                - 0.18 * alpha_beta
                - 0.08 * slow_ratio
            ),
            "anxiety_idx": self._scale_score(
                0.32 * gamma_ratio
                + 0.30 * beta_ratio
                + 0.20 * engagement
                + 0.14 * theta_beta
                - 0.18 * alpha_beta
            ),
            "weakness_idx": self._scale_score(
                0.36 * slow_ratio
                + 0.24 * theta_alpha_beta
                + 0.18 * alpha_beta
                - 0.24 * engagement
                - 0.20 * beta_ratio
                - 0.12 * gamma_ratio
            ),
        }
        if self.smoothed_indices is None:
            self.smoothed_indices = indices
        else:
            self.smoothed_indices = {
                key: self.ema_alpha * value + (1 - self.ema_alpha) * self.smoothed_indices[key]
                for key, value in indices.items()
            }
        smoothed = {key: float(value) for key, value in self.smoothed_indices.items()}
        self.index_history.append(smoothed)
        return smoothed

    def _trend(self, key):
        if len(self.index_history) < 4:
            return 0.0
        values = [item[key] for item in self.index_history]
        recent = float(np.mean(values[-3:]))
        previous = float(np.mean(values[:3]))
        return recent - previous

    def _mean_index(self, key, window=5):
        if not self.index_history:
            return 0.0
        values = [item[key] for item in list(self.index_history)[-window:]]
        return float(np.mean(values))

    def _infer_emotion(self, indices, z):
        reason_codes = []
        candidates = {
            "fatigue": indices["fatigue_idx"],
            "stress": indices["stress_idx"],
            "anxiety": indices["anxiety_idx"],
            "weakness": indices["weakness_idx"],
        }
        trends = {
            "fatigue": self._trend("fatigue_idx"),
            "stress": self._trend("stress_idx"),
            "anxiety": self._trend("anxiety_idx"),
            "weakness": self._trend("weakness_idx"),
        }
        mean_indices = {
            "fatigue": self._mean_index("fatigue_idx"),
            "stress": self._mean_index("stress_idx"),
            "anxiety": self._mean_index("anxiety_idx"),
            "weakness": self._mean_index("weakness_idx"),
        }

        if indices["fatigue_idx"] >= 59 and (z[1] > 0.22 or z[5] > 0.22 or trends["fatigue"] > 2.6 or mean_indices["fatigue"] >= 61):
            reason_codes.append("theta_beta_supported")
        if indices["fatigue_idx"] >= 57 and trends["fatigue"] > 3.2:
            reason_codes.append("fatigue_trend_rise")
        if indices["stress_idx"] >= 59 and (z[6] > 0.22 or z[3] > 0.22 or trends["stress"] > 2.6 or mean_indices["stress"] >= 61):
            reason_codes.append("beta_engagement_supported")
        if indices["anxiety_idx"] >= 59 and (z[7] > 0.22 or z[6] > 0.22 or trends["anxiety"] > 2.6 or mean_indices["anxiety"] >= 61):
            reason_codes.append("beta_gamma_supported")
        if indices["weakness_idx"] >= 59 and (z[5] > 0.22 or trends["weakness"] > 2.6 or mean_indices["weakness"] >= 61):
            reason_codes.append("slow_wave_supported")

        top_name, top_value = max(candidates.items(), key=lambda item: item[1])
        sorted_values = sorted(candidates.values(), reverse=True)
        margin = sorted_values[0] - sorted_values[1] if len(sorted_values) > 1 else sorted_values[0]
        top_supported = any(
            code.startswith(top_name) or
            (top_name == "fatigue" and code in {"theta_beta_supported", "fatigue_trend_rise"}) or
            (top_name == "stress" and code == "beta_engagement_supported") or
            (top_name == "anxiety" and code == "beta_gamma_supported") or
            (top_name == "weakness" and code == "slow_wave_supported")
            for code in reason_codes
        )

        top_mean = mean_indices[top_name]

        if top_value >= 68 and margin >= 3.5 and top_supported:
            candidate = top_name
        elif top_mean >= 61 and top_value >= 60 and top_supported:
            candidate = top_name
            reason_codes.append(f"{top_name}_mean_{top_mean:.1f}")
        elif top_value >= 63 and trends[top_name] > 3.0 and top_supported:
            candidate = top_name
        elif max(candidates.values()) <= 58 and max(mean_indices.values()) <= 60:
            candidate = "normal"
        else:
            candidate = self.last_emotion if self.last_emotion != "normal" and top_value >= 61 and top_mean >= 60 and top_supported else "normal"

        if candidate != self.pending_emotion:
            self.pending_emotion = candidate
            self.hold_counter = 1
        else:
            self.hold_counter += 1

        if candidate == "normal":
            required_hold = 1
        elif top_value >= 68:
            required_hold = 2
        else:
            required_hold = 3
        if self.hold_counter >= required_hold:
            self.last_emotion = candidate

        if self.last_emotion == "normal":
            reason_codes.append("within_personal_baseline")
        reason_codes.append(f"top_index_{top_name}_{top_value:.1f}")
        reason_codes.append(f"top_mean_{top_name}_{top_mean:.1f}")
        if trends[top_name] > 1.5:
            reason_codes.append(f"{top_name}_trend_{trends[top_name]:.1f}")

        return self.last_emotion, reason_codes

    def _maybe_update_baseline(self, feats, emotion, indices):
        if self.baseline_mean is None or self.baseline_std is None:
            return
        max_index = max(indices.values())
        if emotion == "normal" and max_index < 60:
            alpha = self.normal_baseline_alpha
        elif emotion == "normal" and max_index < 62:
            alpha = self.mild_baseline_alpha
        else:
            return
        self.baseline_mean = (1 - alpha) * self.baseline_mean + alpha * feats
        delta = feats - self.baseline_mean
        self.baseline_std = np.maximum(
            (1 - alpha) * self.baseline_std + alpha * np.abs(delta),
            0.04,
        )

    def analyze(self, eeg_power, signal_quality, attention=None, meditation=None):
        feats = self._extract_features(eeg_power)
        quality_level = self._quality_level(signal_quality)
        clean_signal = self._is_signal_clean(signal_quality)

        if quality_level == "no_contact":
            return self._invalid_result(
                "no_contact",
                signal_quality,
                quality_level,
                attention,
                meditation,
                feats,
                ["device_online_waiting_for_contact"],
            )

        if not clean_signal:
            reason_codes = ["poor_signal"]
            if quality_level == "bad_contact":
                reason_codes = ["bad_contact_signal"]
            elif quality_level == "unknown":
                reason_codes = ["unknown_signal_quality"]
            return self._invalid_result(
                "poor_signal",
                signal_quality,
                quality_level,
                attention,
                meditation,
                feats,
                reason_codes,
            )

        quality_reason_codes = []
        if quality_level == "noisy":
            quality_reason_codes.append("noisy_signal")
        if signal_quality in WEAK_CONTACT_SIGNAL_VALUES:
            quality_reason_codes.append("weak_contact_signal")

        elapsed = time.time() - self.start_time
        if not self.is_baseline_ready():
            self.baseline_features.append(feats)
            progress_by_time = elapsed / max(self.baseline_sec, 1)
            progress_by_count = len(self.baseline_features) / max(MIN_BASELINE_SAMPLES, 1)
            progress = min(1.0, progress_by_time, progress_by_count)
            if elapsed >= self.baseline_sec and len(self.baseline_features) >= MIN_BASELINE_SAMPLES:
                self._build_baseline()
            return {
                "status": "calibrating",
                "valid_current": False,
                "model_type": "rule_based_eeg_state_estimation",
                "calibration_progress": progress,
                "signal_quality": signal_quality,
                "quality_level": quality_level,
                "attention": attention,
                "meditation": meditation,
                "emotion": "normal",
                "emotion_zh": self.STATUS_NAMES_ZH["calibrating"],
                "probs": {},
                "indices": self._empty_indices(),
                "features": self._feature_dict(feats),
                "baseline_warning": self._baseline_warning(feats),
                "reason_codes": ["baseline_calibrating", *quality_reason_codes],
            }

        z = self._zscore(feats)
        indices = self._build_indices(z)
        emotion, reason_codes = self._infer_emotion(indices, z)
        reason_codes = [*reason_codes, *quality_reason_codes]
        self._maybe_update_baseline(feats, emotion, indices)

        return {
            "status": "ok",
            "valid_current": True,
            "model_type": "rule_based_eeg_state_estimation",
            "calibration_progress": 1.0,
            "signal_quality": signal_quality,
            "quality_level": quality_level,
            "attention": attention,
            "meditation": meditation,
            "emotion": emotion,
            "emotion_zh": self.EMOTION_NAMES_ZH[emotion],
            "probs": {},
            "indices": indices,
            "features": self._feature_dict(feats, z),
            "baseline_warning": self._baseline_warning(feats, indices),
            "reason_codes": reason_codes,
        }


class EEGWorker(threading.Thread):
    def __init__(self, worker_id, port, baud):
        super().__init__(daemon=True)
        self.worker_id = worker_id
        self.port_str = port
        self.stop_event = threading.Event()
        self.parser = TGAMParser()
        self.analyzer = EEGAnalyzer(baseline_sec=BASELINE_SEC)
        self.raw_buffer = deque(maxlen=WINDOW_SIZE)
        self.raw_since_last = []
        self.last_signal_quality = 0
        self.last_attention = None
        self.last_meditation = None
        self.raw_filter_zi = None
        self.ser = None
        self.baud = baud
        self.last_debug_log_time = 0.0
        self.total_raw_count = 0
        self.total_eeg_power_count = 0
        self.total_sse_payload_count = 0
        self.subscribers = set()
        self.subscribers_lock = threading.Lock()
        self.active_stream_id = None
        self.active_stream_lock = threading.Lock()

    def _open_serial(self):
        if self.ser is None or not self.ser.is_open:
            self.ser = serial.Serial(self.port_str, self.baud, timeout=0.1)
            logger.info("serial opened | worker=%s port=%s", self.worker_id, self.port_str)

    def run(self):
        try:
            self._open_serial()
            while not self.stop_event.is_set():
                chunk = self.ser.read(256)
                if not chunk:
                    continue

                self._debug_log_chunk(len(chunk))
                events = self.parser.feed(chunk)
                eeg_power_event = None

                for event in events:
                    event_type = event["type"]
                    if event_type == "raw":
                        raw_value = event["value"]
                        self.raw_buffer.append(raw_value)
                        self.raw_since_last.append(raw_value)
                        self.total_raw_count += 1
                    elif event_type == "signal":
                        self.last_signal_quality = event["value"]
                    elif event_type == "attention":
                        self.last_attention = event["value"]
                    elif event_type == "meditation":
                        self.last_meditation = event["value"]
                    elif event_type == "eeg_power":
                        eeg_power_event = event["value"]
                        self.total_eeg_power_count += 1
                        self._debug_log_eeg_power(eeg_power_event)

                if eeg_power_event is not None:
                    result = self.analyzer.analyze(
                        eeg_power_event,
                        self.last_signal_quality,
                        attention=self.last_attention,
                        meditation=self.last_meditation,
                    )
                    result["workerId"] = self.worker_id
                    result["port"] = self.port_str
                    result["raw_powers"] = eeg_power_event
                    result["raw_wave"] = self._get_raw_wave_chunk()
                    result["wave_fs"] = TARGET_FS
                    result["analysis_time"] = datetime.utcnow().isoformat() + "Z"
                    self.total_sse_payload_count += 1
                    self._debug_log_payload(result)
                    self._publish(result)

                time.sleep(0.01)
        except Exception as exc:
            logger.exception("worker crashed | worker=%s port=%s error=%s", self.worker_id, self.port_str, exc)
        finally:
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                    logger.info("serial closed | worker=%s port=%s", self.worker_id, self.port_str)
            except Exception:
                pass

    def stop(self):
        self.stop_event.set()

    def register_stream(self):
        stream_id = f"{self.worker_id}-{time.time_ns()}"
        with self.active_stream_lock:
            self.active_stream_id = stream_id
        return stream_id

    def is_stream_active(self, stream_id):
        with self.active_stream_lock:
            return self.active_stream_id == stream_id

    def clear_stream(self, stream_id):
        with self.active_stream_lock:
            if self.active_stream_id == stream_id:
                self.active_stream_id = None

    def subscribe(self):
        subscriber_queue = queue.Queue(maxsize=20)
        with self.subscribers_lock:
            self.subscribers.add(subscriber_queue)
        return subscriber_queue

    def unsubscribe(self, subscriber_queue):
        with self.subscribers_lock:
            self.subscribers.discard(subscriber_queue)

    def _publish(self, result):
        with self.subscribers_lock:
            subscribers = list(self.subscribers)

        for subscriber_queue in subscribers:
            try:
                subscriber_queue.put(result, block=False)
            except queue.Full:
                try:
                    _ = subscriber_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber_queue.put(result, block=False)
                except queue.Full:
                    pass

    def _get_raw_wave_chunk(self):
        if self.raw_since_last:
            samples = self._filter_raw_samples(self.raw_since_last)[::DOWNSAMPLE_FACTOR]
            self.raw_since_last.clear()
        else:
            samples = self._filter_raw_samples(list(self.raw_buffer), update_state=False)[::DOWNSAMPLE_FACTOR]

        if len(samples) > 128:
            samples = samples[-128:]
        return [float(round(value, 3)) for value in samples]

    def _filter_raw_samples(self, samples, update_state=True):
        if not samples:
            return []
        arr = np.asarray(samples, dtype=np.float64)
        if arr.size < max(len(BP_A), len(BP_B)) * 3:
            arr = arr - np.mean(arr)
            return arr.tolist()

        if update_state:
            if self.raw_filter_zi is None:
                self.raw_filter_zi = lfilter_zi(BP_B, BP_A) * arr[0]
            filtered, self.raw_filter_zi = lfilter(BP_B, BP_A, arr, zi=self.raw_filter_zi)
        else:
            zi = lfilter_zi(BP_B, BP_A) * arr[0]
            filtered, _ = lfilter(BP_B, BP_A, arr, zi=zi)
        return filtered.tolist()

    def _should_log_debug(self):
        now = time.time()
        if now - self.last_debug_log_time >= 2:
            self.last_debug_log_time = now
            return True
        return False

    def _debug_log_chunk(self, chunk_len):
        if self._should_log_debug():
            logger.info(
                "serial chunk | worker=%s chunk=%s raw_total=%s eeg_power_total=%s",
                self.worker_id,
                chunk_len,
                self.total_raw_count,
                self.total_eeg_power_count,
            )

    def _debug_log_eeg_power(self, eeg_power):
        logger.info(
            "eeg power | worker=%s delta=%s theta=%s low_alpha=%s high_alpha=%s low_beta=%s high_beta=%s",
            self.worker_id,
            eeg_power.get("delta"),
            eeg_power.get("theta"),
            eeg_power.get("low_alpha"),
            eeg_power.get("high_alpha"),
            eeg_power.get("low_beta"),
            eeg_power.get("high_beta"),
        )

    def _debug_log_payload(self, result):
        logger.info(
            "analysis payload | worker=%s payload_total=%s status=%s emotion=%s raw_wave_len=%s",
            self.worker_id,
            self.total_sse_payload_count,
            result.get("status"),
            result.get("emotion"),
            len(result.get("raw_wave", [])),
        )


workers = OrderedDict()
workers_lock = threading.Lock()
config_lock = threading.Lock()


def normalize_device(item, index=0):
    worker_id = int(item.get("workerId") or item.get("value") or index + 1)
    port = str(item.get("port") or "").strip()
    if not port:
        raise ValueError("port is required")
    name = str(item.get("name") or f"EEG {worker_id}").strip()
    return {
        "workerId": worker_id,
        "value": worker_id,
        "name": name,
        "port": port,
        "enabled": bool(item.get("enabled", True)),
    }


def load_device_config():
    with config_lock:
        if not os.path.exists(CONFIG_FILE):
            devices = []
            save_device_config(devices)
            return devices

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                raw = json.load(file)
            source = raw if isinstance(raw, list) else raw.get("devices", [])
            return [normalize_device(item, index) for index, item in enumerate(source)]
        except Exception as exc:
            logger.exception("failed to load eeg config | file=%s error=%s", CONFIG_FILE, exc)
            return []


def save_device_config(devices):
    directory = os.path.dirname(os.path.abspath(CONFIG_FILE))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(devices, file, ensure_ascii=False, indent=2)


def get_port_mapping():
    return {
        device["workerId"]: device["port"]
        for device in load_device_config()
        if device.get("enabled", True)
    }


def stop_removed_or_changed_workers(next_mapping):
    with workers_lock:
        for worker_id, worker in list(workers.items()):
            if next_mapping.get(worker_id) != worker.port_str:
                worker.stop()
                workers.pop(worker_id, None)


def get_or_create_worker(worker_id):
    port_mapping = get_port_mapping()
    if not port_mapping:
        raise ValueError("no eeg devices configured")
    port = port_mapping.get(worker_id)
    if not port:
        raise ValueError(f"worker {worker_id} is not configured")

    with workers_lock:
        if worker_id in workers:
            workers.move_to_end(worker_id)
            return workers[worker_id]

        if len(workers) >= MAX_WORKERS:
            _, old_worker = workers.popitem(last=False)
            old_worker.stop()

        worker = EEGWorker(worker_id, port, BAUDRATE)
        workers[worker_id] = worker
        worker.start()
        return worker


@app.get("/")
def index():
    return {
        "service": "eeg-stream",
        "status": "ok",
        "default_worker_id": DEFAULT_WORKER_ID,
        "default_port": DEFAULT_PORT,
        "stream_url": "/eeg/stream",
    }


@app.get("/eeg/health")
def health():
    return {
        "status": "ok",
        "default_worker_id": DEFAULT_WORKER_ID,
        "default_port": DEFAULT_PORT,
        "available_workers": list(get_port_mapping().keys()),
    }


@app.get("/eeg/devices")
def list_eeg_devices():
    return {"data": load_device_config()}


@app.get("/eeg/ports")
def list_eeg_ports():
    return {"data": [device["port"] for device in load_device_config()]}


@app.post("/eeg/devices")
def save_eeg_device():
    payload = request.get_json(silent=True) or {}
    try:
        device = normalize_device(payload)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}, 400

    devices = load_device_config()
    updated = False
    for index, item in enumerate(devices):
        if item["workerId"] == device["workerId"]:
            devices[index] = device
            updated = True
            break
    if not updated:
        devices.append(device)

    save_device_config(devices)
    stop_removed_or_changed_workers(get_port_mapping())
    return {"data": device}


@app.delete("/eeg/devices/<int:worker_id>")
def remove_eeg_device(worker_id):
    devices = load_device_config()
    next_devices = [device for device in devices if device["workerId"] != worker_id]
    if len(next_devices) == len(devices):
        return {"status": "error", "message": "device not found"}, 404

    save_device_config(next_devices)
    stop_removed_or_changed_workers(get_port_mapping())
    return {"status": "ok"}


@app.route("/eeg/stream")
def sse_stream():
    requested_worker_id = request.args.get("workerId", default=DEFAULT_WORKER_ID, type=int)
    requested_port = str(request.args.get("port", "")).strip()
    port_mapping = get_port_mapping()
    if not port_mapping:
        return {"status": "error", "message": "no eeg devices configured"}, 404
    if requested_port:
        worker_id = next(
            (item_worker_id for item_worker_id, item_port in port_mapping.items() if item_port == requested_port),
            None,
        )
        if worker_id is None:
            return {"status": "error", "message": f"port {requested_port} is not configured"}, 404
    else:
        worker_id = requested_worker_id if requested_worker_id in port_mapping else next(iter(port_mapping.keys()))
    worker = get_or_create_worker(worker_id)
    stream_id = worker.register_stream()
    subscriber_queue = worker.subscribe()
    sent_count = 0
    ip = request.remote_addr  # ✅ 提前保存

    logger.info("sse connected | ip=%s worker=%s port=%s stream=%s", request.remote_addr, worker_id, worker.port_str, stream_id)

    def event_stream():
        nonlocal sent_count
        try:
            while True:
                if not worker.is_stream_active(stream_id):
                    logger.info("sse superseded | worker=%s old_stream=%s", worker_id, stream_id)
                    break

                try:
                    data = subscriber_queue.get(timeout=0.5)
                    sent_count += 1
                    logger.info(
                        "sse sent | worker=%s stream=%s count=%s status=%s emotion=%s raw_wave_len=%s",
                        worker_id,
                        stream_id,
                        sent_count,
                        data.get("status"),
                        data.get("emotion"),
                        len(data.get("raw_wave", [])),
                    )
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            worker.unsubscribe(subscriber_queue)
            worker.clear_stream(stream_id)
            # logger.info("sse disconnected | ip=%s worker=%s stream=%s", request.remote_addr, worker_id, stream_id)
            # ✅ 用缓存的 ip
            logger.info("sse disconnected | ip=%s worker=%s stream=%s",
                        ip, worker_id, stream_id)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


if __name__ == "__main__":
    logger.info("EEG server start | default_port=%s", DEFAULT_PORT)
    app.run(host="0.0.0.0", port=5000, threaded=True)
