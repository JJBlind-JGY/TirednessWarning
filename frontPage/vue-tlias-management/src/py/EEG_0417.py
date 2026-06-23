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
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import numpy as np
from flask import Flask, Response, request
from scipy.signal import butter, iirnotch, lfilter, lfilter_zi, sosfilt, sosfilt_zi, tf2sos
from scipy.special import softmax

try:
    import serial
except Exception:
    serial = None


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


MAX_WORKERS = max(1, int(os.environ.get("EEG_MAX_WORKERS", "32")))
DEFAULT_WORKER_ID = 1
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get("EEG_CONFIG_FILE", os.path.join(BASE_DIR, "config", "eeg-devices.json"))
HTTP_TIMEOUT_SEC = float(os.environ.get("EEG_HTTP_TIMEOUT_SEC", "2.0"))
HTTP_IDLE_POLL_SEC = float(os.environ.get("EEG_HTTP_IDLE_POLL_SEC", "0.1"))
HTTP_RETRY_MAX_SEC = float(os.environ.get("EEG_HTTP_RETRY_MAX_SEC", "5.0"))
HTTP_FETCH_LIMIT = max(32, min(int(os.environ.get("EEG_HTTP_FETCH_LIMIT", "512")), 512))
BAUDRATE = int(os.environ.get("EEG_SERIAL_BAUD", "57600"))
SERIAL_SILENCE_OFFLINE_SEC = float(os.environ.get("EEG_SERIAL_SILENCE_OFFLINE_SEC", "3.0"))

RAW_FS = 512
TARGET_FS = 128
SAMPLE_SEC = 4
WINDOW_SIZE = RAW_FS * SAMPLE_SEC
DOWNSAMPLE_FACTOR = RAW_FS // TARGET_FS
BP_B, BP_A = butter(4, [1 / (RAW_FS / 2), 40 / (RAW_FS / 2)], btype="band")
DISPLAY_NOTCH_B, DISPLAY_NOTCH_A = iirnotch(50, 30, fs=RAW_FS)
DISPLAY_SOS = np.vstack((
    tf2sos(DISPLAY_NOTCH_B, DISPLAY_NOTCH_A),
    butter(4, [0.5, 35], btype="bandpass", fs=RAW_FS, output="sos"),
))
BASELINE_SEC = 30
MIN_BASELINE_SAMPLES = 10
NO_CONTACT_BASELINE_RESET_SEC = 30.0
NO_CONTACT_SIGNAL_VALUE = 200
POOR_SIGNAL_THRESHOLD = 100
STRONG_BAD_CONTACT_SIGNAL_VALUES = {107}
WEAK_CONTACT_SIGNAL_VALUES = {29, 54, 55, 56, 80, 81, 82}
BAD_CONTACT_SIGNAL_VALUES = STRONG_BAD_CONTACT_SIGNAL_VALUES | WEAK_CONTACT_SIGNAL_VALUES
BLOCKING_SIGNAL_VALUES = STRONG_BAD_CONTACT_SIGNAL_VALUES | {NO_CONTACT_SIGNAL_VALUE}
BASELINE_MAX_SAMPLES = 180
SNAPSHOT_CACHE_SEC = 30
RAW_TGAM_CACHE_SEC = SNAPSHOT_CACHE_SEC + 5

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

    def __init__(self, baseline_sec=BASELINE_SEC, baseline_reset_reason="worker_created"):
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
        self.no_contact_started_at = None
        self.baseline_reset_reason = baseline_reset_reason
        self.baseline_reset_at = datetime.utcnow().isoformat() + "Z"

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

    def reset_baseline(self, reason):
        self.start_time = time.time()
        self.baseline_features.clear()
        self.baseline_mean = None
        self.baseline_std = None
        self.smoothed_indices = None
        self.index_history.clear()
        self._reset_current_prediction()
        self.baseline_reset_reason = reason
        self.baseline_reset_at = datetime.utcnow().isoformat() + "Z"
        logger.info("eeg baseline reset | reason=%s", reason)

    def _has_baseline_state(self):
        return self.baseline_mean is not None or bool(self.baseline_features)

    def _mark_contact_state(self, quality_level):
        now = time.time()
        if quality_level == "no_contact":
            if self.no_contact_started_at is None:
                self.no_contact_started_at = now
            no_contact_elapsed = now - self.no_contact_started_at
            if no_contact_elapsed >= NO_CONTACT_BASELINE_RESET_SEC and self._has_baseline_state():
                self.reset_baseline("no_contact_timeout")
            return no_contact_elapsed
        if self.no_contact_started_at is not None and not self.is_baseline_ready():
            self.start_time = now
            self.baseline_features.clear()
        self.no_contact_started_at = None
        return 0.0

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
            "baseline_reset_reason": self.baseline_reset_reason,
            "baseline_reset_at": self.baseline_reset_at,
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
        self.baseline_reset_reason = ""
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
        no_contact_elapsed = self._mark_contact_state(quality_level)

        if quality_level == "no_contact":
            return self._invalid_result(
                "no_contact",
                signal_quality,
                quality_level,
                attention,
                meditation,
                feats,
                [
                    "device_online_waiting_for_contact",
                    f"no_contact_elapsed_{no_contact_elapsed:.1f}s",
                ],
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
                "baseline_reset_reason": self.baseline_reset_reason,
                "baseline_reset_at": self.baseline_reset_at,
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
            "baseline_reset_reason": self.baseline_reset_reason,
            "baseline_reset_at": self.baseline_reset_at,
        }


class WifiEEGWorker(threading.Thread):
    def __init__(self, worker_id, base_url, baseline_reset_reason="worker_created"):
        super().__init__(daemon=True)
        self.worker_id = worker_id
        self.transport = "wifi"
        self.base_url = base_url.rstrip("/")
        self.port_str = ""
        self.baud = BAUDRATE
        self.stop_event = threading.Event()
        self.analyzer = EEGAnalyzer(baseline_sec=BASELINE_SEC, baseline_reset_reason=baseline_reset_reason)
        self.raw_buffer = deque(maxlen=WINDOW_SIZE)
        self.raw_since_last = []
        self.raw_tgam_history = deque(maxlen=RAW_FS * RAW_TGAM_CACHE_SEC)
        self.snapshot_history = deque(maxlen=SNAPSHOT_CACHE_SEC * 2)
        self.snapshot_lock = threading.Lock()
        self.last_signal_quality = 0
        self.contact_blocked = False
        self.last_attention = None
        self.last_meditation = None
        self.raw_filter_zi = None
        self.display_filter_zi = None
        self.last_debug_log_time = 0.0
        self.total_raw_count = 0
        self.total_eeg_power_count = 0
        self.total_sse_payload_count = 0
        self.error_count = 0
        self.dropped_sample_count = 0
        self.sample_cursor = None
        self.device_boot_id = None
        self.device_id = ""
        self.device_rssi = None
        self.last_summary_index = None
        self.last_success_at = None
        self.last_sample_at = None
        self.sample_lag_ms = None
        self.subscribers = set()
        self.subscribers_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.status = "connecting"
        self.last_payload_at = None
        self.last_error = ""
        self.started_at = datetime.utcnow().isoformat() + "Z"

    def _set_status(self, status, error=""):
        with self.status_lock:
            self.status = status
            self.last_error = str(error or "")

    def _subscriber_count(self):
        with self.subscribers_lock:
            return len(self.subscribers)

    def status_payload(self, status=None, error=None):
        with self.status_lock:
            current_status = status or self.status
            current_error = self.last_error if error is None else str(error or "")
            last_payload_at = self.last_payload_at
        quality_level = self.analyzer._quality_level(self.last_signal_quality)
        if status is None and self.contact_blocked:
            current_status = "no_contact" if quality_level == "no_contact" else "poor_signal"
        return {
            "workerId": self.worker_id,
            "transport": self.transport,
            "baseUrl": self.base_url,
            "port": self.port_str,
            "baud": self.baud,
            "status": current_status,
            "valid_current": False,
            "raw_wave": [],
            "raw_powers": {},
            "indices": {},
            "probs": {},
            "features": {},
            "reason_codes": [current_error] if current_error else [],
            "message": current_error,
            "signal_quality": self.last_signal_quality,
            "quality_level": quality_level,
            "last_payload_at": last_payload_at,
            "subscriber_count": self._subscriber_count(),
            "raw_count": self.total_raw_count,
            "eeg_power_count": self.total_eeg_power_count,
            "payload_count": self.total_sse_payload_count,
            "error_count": self.error_count,
            "dropped_sample_count": self.dropped_sample_count,
            "sample_cursor": self.sample_cursor,
            "device_boot_id": self.device_boot_id,
            "device_id": self.device_id,
            "device_rssi": self.device_rssi,
            "last_success_at": self.last_success_at,
            "last_sample_at": self.last_sample_at,
            "sample_lag_ms": self.sample_lag_ms,
            "started_at": self.started_at,
            "baseline_reset_reason": self.analyzer.baseline_reset_reason,
            "baseline_reset_at": self.analyzer.baseline_reset_at,
            "baseline_ready": self.analyzer.is_baseline_ready(),
        }

    def connection_key(self):
        return f"wifi:{self.base_url}"

    def _fetch_payload(self):
        query = urlencode({
            "after": 0 if self.sample_cursor is None else self.sample_cursor,
            "limit": HTTP_FETCH_LIMIT,
        })
        req = Request(
            f"{self.base_url}/api/eeg?{query}",
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        with urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
            if response.status != 200:
                raise RuntimeError(f"device returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

    def _reset_transport_state(self, reason):
        self.raw_buffer.clear()
        self.raw_since_last.clear()
        self.raw_filter_zi = None
        self.display_filter_zi = None
        self.last_summary_index = None
        self.analyzer.reset_baseline(reason)

    def _validate_payload(self, payload):
        if int(payload.get("schemaVersion", 0)) != 1:
            raise ValueError("unsupported EEG device schema")
        sample_rate = int(payload.get("sampleRateHz", 0))
        if sample_rate != RAW_FS:
            raise ValueError(f"unsupported sample rate: {sample_rate}")
        if not isinstance(payload.get("samples"), list):
            raise ValueError("device samples must be an array")

    def _consume_samples(self, payload, received_at_ms, accept_samples=True):
        start_index = int(payload.get("startIndex", 0))
        returned_until = int(payload.get("returnedUntilIndex", start_index))
        samples = [int(value) for value in payload.get("samples", [])]
        if returned_until - start_index != len(samples):
            raise ValueError("device sample range does not match payload length")

        if self.sample_cursor is not None and start_index > self.sample_cursor:
            self.dropped_sample_count += start_index - self.sample_cursor
            self._reset_transport_state("sample_gap")
        elif self.sample_cursor is not None and start_index < self.sample_cursor:
            duplicate_count = min(len(samples), self.sample_cursor - start_index)
            samples = samples[duplicate_count:]
            start_index += duplicate_count

        device_next = int(payload.get("nextSampleIndex", returned_until))
        for offset, raw_value in enumerate(samples):
            sample_index = start_index + offset
            samples_behind = max(0, device_next - 1 - sample_index)
            sample_ts = received_at_ms - int(samples_behind * 1000 / RAW_FS)
            self.total_raw_count += 1
            if not accept_samples:
                continue
            self.raw_buffer.append(raw_value)
            self.raw_since_last.append(raw_value)
            self._remember_raw_tgam(raw_value, sample_ts)

        self.sample_cursor = returned_until
        if samples and accept_samples:
            self.last_sample_at = datetime.utcnow().isoformat() + "Z"
        self.sample_lag_ms = max(0, int((device_next - returned_until) * 1000 / RAW_FS))
        return returned_until < device_next, samples if accept_samples else []

    def _contact_state(self, signal_quality):
        quality_level = self.analyzer._quality_level(signal_quality)
        blocked = quality_level in {"no_contact", "bad_contact", "poor", "unknown"}
        status = "no_contact" if quality_level == "no_contact" else "poor_signal"
        return blocked, status, quality_level

    def _update_contact_state(self, signal_quality):
        blocked, status, quality_level = self._contact_state(signal_quality)
        changed = blocked != self.contact_blocked
        self.contact_blocked = blocked
        self.last_signal_quality = signal_quality
        if blocked:
            self.raw_buffer.clear()
            self.raw_since_last.clear()
            self.raw_filter_zi = None
            self.display_filter_zi = None
        return changed, blocked, status, quality_level

    def _build_analysis_payload(self, payload):
        bands = payload.get("bands") or {}
        eeg_power = {
            "delta": int(bands.get("delta", 0)),
            "theta": int(bands.get("theta", 0)),
            "low_alpha": int(bands.get("lowAlpha", 0)),
            "high_alpha": int(bands.get("highAlpha", 0)),
            "low_beta": int(bands.get("lowBeta", 0)),
            "high_beta": int(bands.get("highBeta", 0)),
            "low_gamma": int(bands.get("lowGamma", 0)),
            "mid_gamma": int(bands.get("midGamma", 0)),
        }
        if not any(eeg_power.values()):
            return None

        self.last_signal_quality = int(payload.get("poorSignal", self.last_signal_quality))
        self.last_attention = payload.get("attention")
        self.last_meditation = payload.get("meditation")
        self.total_eeg_power_count += 1
        self._debug_log_eeg_power(eeg_power)
        result = self.analyzer.analyze(
            eeg_power,
            self.last_signal_quality,
            attention=self.last_attention,
            meditation=self.last_meditation,
        )
        original_wave = [int(value) for value in self.raw_since_last[-RAW_FS:]]
        display_wave = self._filter_display_samples(original_wave, update_state=False)[::DOWNSAMPLE_FACTOR]
        result.update({
            "workerId": self.worker_id,
            "baseUrl": self.base_url,
            "raw_powers": eeg_power,
            "raw_wave": self._get_raw_wave_chunk(),
            "wave_fs": TARGET_FS,
            "raw_wave_original": original_wave,
            "raw_wave_original_fs": RAW_FS,
            "raw_wave_original_live_published": True,
            "raw_wave_display": [float(round(value, 3)) for value in display_wave],
            "display_wave_fs": TARGET_FS,
            "analysis_time": datetime.utcnow().isoformat() + "Z",
            "analysis_ts": int(time.time() * 1000),
            "device_id": self.device_id,
            "device_boot_id": self.device_boot_id,
            "device_rssi": self.device_rssi,
            "dropped_sample_count": self.dropped_sample_count,
        })
        return result

    def run(self):
        retry_delay = 0.5
        self._publish(self.status_payload(status="connecting"))
        while not self.stop_event.is_set():
            try:
                payload = self._fetch_payload()
                self._validate_payload(payload)
                received_at_ms = int(time.time() * 1000)
                boot_id = str(payload.get("bootId", ""))
                if self.device_boot_id is not None and boot_id != self.device_boot_id:
                    self._reset_transport_state("device_restarted")
                    first_available = int(payload.get("firstAvailableIndex", 0))
                    self.sample_cursor = first_available
                    self.device_boot_id = boot_id
                    if int(payload.get("startIndex", first_available)) > first_available:
                        continue
                self.device_boot_id = boot_id
                self.device_id = str(payload.get("deviceId", ""))
                self.device_rssi = payload.get("rssi")
                signal_quality = int(payload.get("poorSignal", self.last_signal_quality))
                contact_changed, contact_blocked, contact_status, quality_level = self._update_contact_state(
                    signal_quality
                )
                has_backlog, accepted_samples = self._consume_samples(
                    payload,
                    received_at_ms,
                    accept_samples=not contact_blocked,
                )
                if contact_changed and contact_blocked:
                    self._publish({
                        **self.status_payload(status=contact_status),
                        "signal_quality": signal_quality,
                        "quality_level": quality_level,
                    })
                if accepted_samples:
                    display_samples = self._filter_display_samples(accepted_samples)[::DOWNSAMPLE_FACTOR]
                    self._publish({
                        "workerId": self.worker_id,
                        "baseUrl": self.base_url,
                        "status": "online",
                        "payload_type": "raw_wave",
                        "signal_quality": signal_quality,
                        "quality_level": quality_level,
                        "raw_wave_original": accepted_samples,
                        "raw_wave_original_fs": RAW_FS,
                        "raw_wave_display": [float(round(value, 3)) for value in display_samples],
                        "display_wave_fs": TARGET_FS,
                        "sample_cursor": self.sample_cursor,
                        "device_boot_id": self.device_boot_id,
                        "device_id": self.device_id,
                        "device_rssi": self.device_rssi,
                        "dropped_sample_count": self.dropped_sample_count,
                        "sample_lag_ms": self.sample_lag_ms,
                    })

                summary_index = int(payload.get("summaryIndex", 0))
                if summary_index != self.last_summary_index:
                    self.last_summary_index = summary_index
                    result = self._build_analysis_payload(payload)
                    if result is not None:
                        self.last_payload_at = result["analysis_time"]
                        self.total_sse_payload_count += 1
                        self._remember_snapshot(result)
                        self._debug_log_payload(result)
                        self._publish(result)

                self.last_success_at = datetime.utcnow().isoformat() + "Z"
                self._set_status("online")
                retry_delay = 0.5
                if not has_backlog:
                    self.stop_event.wait(HTTP_IDLE_POLL_SEC)
            except (HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
                self.error_count += 1
                status = "offline" if isinstance(exc, (URLError, TimeoutError, OSError)) else "error"
                self._set_status(status, exc)
                self._publish(self.status_payload(status=status, error=exc))
                logger.warning(
                    "wifi eeg read failed | worker=%s url=%s retry=%.1fs error=%s",
                    self.worker_id, self.base_url, retry_delay, exc,
                )
                self.stop_event.wait(retry_delay)
                retry_delay = min(HTTP_RETRY_MAX_SEC, retry_delay * 2)
            except Exception as exc:
                self.error_count += 1
                self._set_status("error", exc)
                self._publish(self.status_payload(status="error", error=exc))
                logger.exception("wifi eeg worker error | worker=%s url=%s", self.worker_id, self.base_url)
                self.stop_event.wait(retry_delay)
                retry_delay = min(HTTP_RETRY_MAX_SEC, retry_delay * 2)
        self._set_status("offline")

    def stop(self):
        self.stop_event.set()

    def subscribe(self):
        subscriber_queue = queue.Queue(maxsize=20)
        with self.subscribers_lock:
            self.subscribers.add(subscriber_queue)
        try:
            subscriber_queue.put(self.status_payload(), block=False)
        except queue.Full:
            pass
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

    def _remember_snapshot(self, result):
        snapshot = json.loads(json.dumps(result, ensure_ascii=False))
        with self.snapshot_lock:
            self.snapshot_history.append(snapshot)

    def _remember_raw_tgam(self, raw_value, sample_ts=None):
        sample = {"ts": int(sample_ts or time.time() * 1000), "value": int(raw_value)}
        with self.snapshot_lock:
            self.raw_tgam_history.append(sample)

    def snapshot(self, seconds=10, before_ms=None):
        before_ms = int(before_ms or time.time() * 1000)
        seconds = max(1, min(int(seconds or 10), SNAPSHOT_CACHE_SEC))
        window_start = before_ms - seconds * 1000
        with self.snapshot_lock:
            payloads = [
                item for item in self.snapshot_history
                if window_start <= int(item.get("analysis_ts") or 0) <= before_ms
            ]
            raw_tgam_samples = [
                item for item in self.raw_tgam_history
                if window_start <= int(item.get("ts") or 0) <= before_ms
            ]
        raw_wave = []
        predictions = []
        for item in payloads:
            raw_wave.extend(item.get("raw_wave") or [])
            prediction = dict(item)
            prediction.pop("raw_wave", None)
            prediction.pop("raw_wave_original", None)
            predictions.append(prediction)
        raw_tgam_values = [item["value"] for item in raw_tgam_samples]
        return {
            "workerId": self.worker_id,
            "windowStart": window_start,
            "windowEnd": before_ms,
            "waveFs": TARGET_FS,
            "rawWave": raw_wave,
            "rawWaveOriginal": raw_tgam_values,
            "rawWaveOriginalFs": RAW_FS,
            "rawTgamFs": RAW_FS,
            "rawTgamSamples": raw_tgam_values,
            "rawTgamCount": len(raw_tgam_values),
            "rawTgamWindowStart": raw_tgam_samples[0]["ts"] if raw_tgam_samples else 0,
            "rawTgamWindowEnd": raw_tgam_samples[-1]["ts"] if raw_tgam_samples else 0,
            "predictions": predictions,
            "predictionCount": len(predictions),
            "partial": len(predictions) == 0 or len(raw_tgam_values) < int(seconds * RAW_FS * 0.8),
        }

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

    def _filter_display_samples(self, samples, update_state=True):
        if samples is None or len(samples) == 0:
            return []
        arr = np.asarray(samples, dtype=np.float64)
        reference = np.asarray(self.raw_buffer, dtype=np.float64)
        if reference.size < 32:
            reference = arr
        center = float(np.median(reference))
        mad = float(np.median(np.abs(reference - center)))
        soft_limit = min(600.0, max(128.0, 6.0 * 1.4826 * mad))
        softened = center + soft_limit * np.tanh((arr - center) / soft_limit)

        if update_state:
            if self.display_filter_zi is None:
                self.display_filter_zi = sosfilt_zi(DISPLAY_SOS) * softened[0]
            filtered, self.display_filter_zi = sosfilt(
                DISPLAY_SOS,
                softened,
                zi=self.display_filter_zi,
            )
        else:
            zi = sosfilt_zi(DISPLAY_SOS) * softened[0]
            filtered, _ = sosfilt(DISPLAY_SOS, softened, zi=zi)
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
                "wifi chunk | worker=%s chunk=%s raw_total=%s eeg_power_total=%s",
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


class SerialEEGWorker(WifiEEGWorker):
    def __init__(self, worker_id, port, baud=BAUDRATE, baseline_reset_reason="worker_created"):
        super().__init__(worker_id, "http://serial.local", baseline_reset_reason=baseline_reset_reason)
        self.transport = "serial"
        self.base_url = ""
        self.port_str = str(port or "").strip()
        self.baud = int(baud or BAUDRATE)
        self.parser = TGAMParser()
        self.ser = None
        self.last_serial_read_at = time.monotonic()

    def connection_key(self):
        return f"serial:{self.port_str}:{self.baud}"

    def _open_serial(self):
        if serial is None:
            raise RuntimeError("pyserial is required for serial EEG devices")
        if self.ser is None or not self.ser.is_open:
            self._set_status("connecting")
            self.ser = serial.Serial(self.port_str, self.baud, timeout=0.1)
            self.last_serial_read_at = time.monotonic()
            self._set_status("online")
            logger.info("serial opened | worker=%s port=%s baud=%s", self.worker_id, self.port_str, self.baud)

    def _build_serial_analysis_payload(self, eeg_power):
        self.total_eeg_power_count += 1
        self._debug_log_eeg_power(eeg_power)
        result = self.analyzer.analyze(
            eeg_power,
            self.last_signal_quality,
            attention=self.last_attention,
            meditation=self.last_meditation,
        )
        original_wave = [int(value) for value in self.raw_since_last[-RAW_FS:]]
        display_wave = self._filter_display_samples(original_wave, update_state=False)[::DOWNSAMPLE_FACTOR]
        result.update({
            "workerId": self.worker_id,
            "transport": self.transport,
            "port": self.port_str,
            "baud": self.baud,
            "raw_powers": eeg_power,
            "raw_wave": self._get_raw_wave_chunk(),
            "wave_fs": TARGET_FS,
            "raw_wave_original": original_wave,
            "raw_wave_original_fs": RAW_FS,
            "raw_wave_original_live_published": True,
            "raw_wave_display": [float(round(value, 3)) for value in display_wave],
            "display_wave_fs": TARGET_FS,
            "analysis_time": datetime.utcnow().isoformat() + "Z",
            "analysis_ts": int(time.time() * 1000),
        })
        return result

    def run(self):
        try:
            self._publish(self.status_payload(status="connecting"))
            self._open_serial()
            while not self.stop_event.is_set():
                chunk = self.ser.read(256)
                if not chunk:
                    if time.monotonic() - self.last_serial_read_at > SERIAL_SILENCE_OFFLINE_SEC:
                        raise TimeoutError(f"serial silent for {SERIAL_SILENCE_OFFLINE_SEC:.1f}s")
                    continue

                self.last_serial_read_at = time.monotonic()
                self.last_success_at = datetime.utcnow().isoformat() + "Z"
                self._debug_log_chunk(len(chunk))
                events = self.parser.feed(chunk)
                eeg_power_event = None

                for event in events:
                    event_type = event["type"]
                    if event_type == "raw":
                        raw_value = int(event["value"])
                        self.total_raw_count += 1
                        self.raw_buffer.append(raw_value)
                        self.raw_since_last.append(raw_value)
                        self._remember_raw_tgam(raw_value)
                        self.last_sample_at = datetime.utcnow().isoformat() + "Z"
                    elif event_type == "signal":
                        self.last_signal_quality = int(event["value"])
                    elif event_type == "attention":
                        self.last_attention = event["value"]
                    elif event_type == "meditation":
                        self.last_meditation = event["value"]
                    elif event_type == "eeg_power":
                        eeg_power_event = event["value"]

                if self.raw_since_last:
                    display_samples = self._filter_display_samples(self.raw_since_last[-RAW_FS:])[::DOWNSAMPLE_FACTOR]
                    self._publish({
                        "workerId": self.worker_id,
                        "transport": self.transport,
                        "port": self.port_str,
                        "baud": self.baud,
                        "status": "online",
                        "payload_type": "raw_wave",
                        "signal_quality": self.last_signal_quality,
                        "quality_level": self.analyzer._quality_level(self.last_signal_quality),
                        "raw_wave_original": [int(value) for value in self.raw_since_last[-RAW_FS:]],
                        "raw_wave_original_fs": RAW_FS,
                        "raw_wave_display": [float(round(value, 3)) for value in display_samples],
                        "display_wave_fs": TARGET_FS,
                    })

                if eeg_power_event is not None:
                    result = self._build_serial_analysis_payload(eeg_power_event)
                    self.last_payload_at = result["analysis_time"]
                    self._set_status("online")
                    self.total_sse_payload_count += 1
                    self._remember_snapshot(result)
                    self._debug_log_payload(result)
                    self._publish(result)
        except Exception as exc:
            self.error_count += 1
            self._set_status("error", exc)
            self._publish(self.status_payload(status="error", error=exc))
            logger.exception("serial eeg worker error | worker=%s port=%s error=%s", self.worker_id, self.port_str, exc)
        finally:
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                    logger.info("serial closed | worker=%s port=%s", self.worker_id, self.port_str)
            except Exception:
                pass
            self._set_status("offline")


EEGWorker = WifiEEGWorker


workers = OrderedDict()
workers_lock = threading.Lock()
config_lock = threading.Lock()


def normalize_device(item, index=0):
    worker_id = int(item.get("workerId") or item.get("value") or index + 1)
    name = str(item.get("name") or f"EEG {worker_id}").strip()
    raw_transport = str(item.get("transport") or "").strip().lower()
    has_base_url = bool(str(item.get("baseUrl") or "").strip())
    has_port = bool(str(item.get("port") or "").strip())
    transport = raw_transport or ("serial" if has_port and not has_base_url else "wifi")
    if transport not in {"wifi", "serial"}:
        raise ValueError("transport must be wifi or serial")

    base_url = str(item.get("baseUrl") or "").strip().rstrip("/")
    port = str(item.get("port") or "").strip()
    baud = int(item.get("baud") or BAUDRATE)

    if transport == "wifi":
        if base_url and "://" not in base_url:
            base_url = f"http://{base_url}"
        parsed = urlparse(base_url)
        hostname = parsed.hostname or ""
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or (hostname != "localhost" and "." not in hostname and ":" not in hostname)
        ):
            raise ValueError("baseUrl must be a valid HTTP URL")
        port = ""
        label = f"{name} / {base_url}"
    else:
        if not port:
            raise ValueError("port is required")
        base_url = ""
        label = f"{name} / {port} / {baud}"

    return {
        "workerId": worker_id,
        "value": worker_id,
        "name": name,
        "transport": transport,
        "baseUrl": base_url,
        "port": port,
        "baud": baud,
        "label": label,
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
    logger.info("eeg config saved | file=%s devices=%s", CONFIG_FILE, len(devices))


def get_device_mapping():
    return {
        device["workerId"]: device
        for device in load_device_config()
        if device.get("enabled", True)
    }


def device_connection_key(device):
    if device.get("transport") == "serial":
        return f"serial:{device.get('port')}:{int(device.get('baud') or BAUDRATE)}"
    return f"wifi:{device.get('baseUrl')}"


def stop_removed_or_changed_workers(next_mapping):
    with workers_lock:
        for worker_id, worker in list(workers.items()):
            next_device = next_mapping.get(worker_id)
            if next_device is None or device_connection_key(next_device) != worker.connection_key():
                worker.stop()
                workers.pop(worker_id, None)


def synchronize_workers():
    device_mapping = get_device_mapping()
    stop_removed_or_changed_workers(device_mapping)
    for worker_id, device in device_mapping.items():
        try:
            worker = get_or_create_worker(worker_id)
            logger.info(
                "eeg worker active | worker=%s transport=%s endpoint=%s alive=%s",
                worker_id,
                device.get("transport"),
                device.get("baseUrl") or device.get("port"),
                worker.is_alive(),
            )
        except Exception:
            logger.exception("failed to start eeg worker | worker=%s device=%s", worker_id, device)
    return device_mapping


def fetch_device_json(url):
    req = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    with urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
        if response.status != 200:
            raise RuntimeError(f"device returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def probe_wifi_device_protocol(device):
    base_url = device["baseUrl"]
    status_payload = fetch_device_json(f"{base_url}/api/status")
    eeg_payload = fetch_device_json(
        f"{base_url}/api/eeg?{urlencode({'after': 0, 'limit': min(32, HTTP_FETCH_LIMIT)})}"
    )
    if int(eeg_payload.get("schemaVersion", 0)) != 1:
        raise ValueError("unsupported EEG device schema")
    if int(eeg_payload.get("sampleRateHz", 0)) != RAW_FS:
        raise ValueError(f"unsupported sample rate: {eeg_payload.get('sampleRateHz')}")
    if not isinstance(eeg_payload.get("samples"), list):
        raise ValueError("device samples must be an array")
    return status_payload, eeg_payload


def probe_serial_device_protocol(device):
    if serial is None:
        raise RuntimeError("pyserial is required for serial EEG devices")
    ser = serial.Serial(device["port"], int(device.get("baud") or BAUDRATE), timeout=0.2)
    try:
        return {"port": device["port"], "baud": int(device.get("baud") or BAUDRATE), "isOpen": ser.is_open}
    finally:
        ser.close()


def probe_device_protocol(device):
    if device.get("transport") == "serial":
        return probe_serial_device_protocol(device)
    return probe_wifi_device_protocol(device)

def remove_worker_if_current(worker_id, worker):
    with workers_lock:
        if workers.get(worker_id) is worker:
            workers.pop(worker_id, None)


def get_or_create_worker(worker_id):
    device_mapping = get_device_mapping()
    if not device_mapping:
        raise ValueError("no eeg devices configured")
    device = device_mapping.get(worker_id)
    if not device:
        raise ValueError(f"worker {worker_id} is not configured")

    with workers_lock:
        baseline_reset_reason = "worker_created"
        if worker_id in workers:
            worker = workers[worker_id]
            if worker.is_alive() and not worker.stop_event.is_set():
                workers.move_to_end(worker_id)
                return worker
            worker.stop()
            workers.pop(worker_id, None)
            baseline_reset_reason = "device_reconnected"

        if len(workers) >= MAX_WORKERS:
            _, old_worker = workers.popitem(last=False)
            old_worker.stop()

        if device.get("transport") == "serial":
            worker = SerialEEGWorker(
                worker_id,
                device["port"],
                int(device.get("baud") or BAUDRATE),
                baseline_reset_reason=baseline_reset_reason,
            )
        else:
            worker = WifiEEGWorker(worker_id, device["baseUrl"], baseline_reset_reason=baseline_reset_reason)
        workers[worker_id] = worker
        worker.start()
        return worker


@app.get("/")
def index():
    return {
        "service": "eeg-stream",
        "transport": "wifi-http+serial-tgam",
        "status": "ok",
        "default_worker_id": DEFAULT_WORKER_ID,
        "stream_url": "/eeg/stream",
    }


@app.get("/eeg/health")
def health():
    device_mapping = get_device_mapping()
    with workers_lock:
        worker_status = {worker_id: worker.status_payload() for worker_id, worker in workers.items()}
    for worker_id, device in device_mapping.items():
        worker_status.setdefault(worker_id, {
            "workerId": worker_id,
            "transport": device.get("transport"),
            "baseUrl": device.get("baseUrl", ""),
            "port": device.get("port", ""),
            "baud": int(device.get("baud") or BAUDRATE),
            "status": "connecting",
            "message": "worker is starting",
            "subscriber_count": 0,
            "dropped_sample_count": 0,
        })
    return {
        "status": "ok",
        "default_worker_id": DEFAULT_WORKER_ID,
        "max_workers": MAX_WORKERS,
        "active_workers": len(worker_status),
        "available_workers": list(device_mapping.keys()),
        "workers": worker_status,
    }


@app.get("/eeg/snapshot")
def eeg_snapshot():
    worker_id = request.args.get("workerId", default=DEFAULT_WORKER_ID, type=int)
    seconds = request.args.get("seconds", default=10, type=int)
    before = request.args.get("before", default=0, type=int)
    with workers_lock:
        worker = workers.get(worker_id)
    if worker is None:
        window_end = int(before or time.time() * 1000)
        return {
            "workerId": worker_id,
            "windowStart": max(0, window_end - max(1, seconds) * 1000),
            "windowEnd": window_end,
            "waveFs": TARGET_FS,
            "rawWave": [],
            "predictions": [],
            "predictionCount": 0,
            "partial": True,
            "message": "worker not running",
        }
    return worker.snapshot(seconds=seconds, before_ms=before)


@app.get("/eeg/devices")
def list_eeg_devices():
    return {"data": load_device_config()}


@app.get("/eeg/devices/<int:worker_id>/probe")
def probe_eeg_device(worker_id):
    device = next((item for item in load_device_config() if item["workerId"] == worker_id), None)
    if device is None:
        return {"status": "error", "message": "device not found"}, 404
    try:
        probe_payload = probe_device_protocol(device)
        worker = get_or_create_worker(worker_id) if device.get("enabled", True) else None
        data = {
            "transport": device.get("transport"),
            "hardwareReachable": True,
            "protocolValid": True,
            "collectorStatus": worker.status_payload() if worker else None,
        }
        if device.get("transport") == "serial":
            data.update({
                "port": probe_payload.get("port"),
                "baud": probe_payload.get("baud"),
                "isOpen": probe_payload.get("isOpen"),
            })
        else:
            status_payload, eeg_payload = probe_payload
            data.update({
                "deviceId": eeg_payload.get("deviceId") or status_payload.get("deviceId"),
                "bootId": eeg_payload.get("bootId"),
                "sampleRateHz": eeg_payload.get("sampleRateHz"),
                "nextSampleIndex": eeg_payload.get("nextSampleIndex"),
                "rssi": eeg_payload.get("rssi", status_payload.get("rssi")),
                "status": status_payload,
            })
        return {"status": "ok", "data": data}
    except Exception as exc:
        logger.warning(
            "eeg probe failed | worker=%s transport=%s endpoint=%s error=%s",
            worker_id,
            device.get("transport"),
            device.get("baseUrl") or device.get("port"),
            exc,
        )
        return {"status": "error", "message": str(exc)}, 502


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
    synchronize_workers()
    return {"data": device}


@app.delete("/eeg/devices/<int:worker_id>")
def remove_eeg_device(worker_id):
    devices = load_device_config()
    next_devices = [device for device in devices if device["workerId"] != worker_id]
    if len(next_devices) == len(devices):
        return {"status": "error", "message": "device not found"}, 404

    save_device_config(next_devices)
    synchronize_workers()
    return {"status": "ok"}


@app.post("/eeg/workers/<int:worker_id>/baseline/reset")
def reset_worker_baseline(worker_id):
    device_mapping = get_device_mapping()
    if not device_mapping:
        return {"status": "error", "message": "no eeg devices configured"}, 404
    if worker_id not in device_mapping:
        return {"status": "error", "message": "worker is not configured"}, 404

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "manual_detail_reset")[:80]
    try:
        worker = get_or_create_worker(worker_id)
        worker.analyzer.reset_baseline(reason)
        return {
            "status": "ok",
            "workerId": worker_id,
            "baseline_reset_reason": worker.analyzer.baseline_reset_reason,
            "baseline_reset_at": worker.analyzer.baseline_reset_at,
            "baseline_ready": worker.analyzer.is_baseline_ready(),
        }
    except Exception as exc:
        logger.warning("manual eeg baseline reset failed | worker=%s error=%s", worker_id, exc)
        return {"status": "error", "message": str(exc)}, 502


@app.route("/eeg/stream")
def sse_stream():
    requested_worker_id = request.args.get("workerId", default=DEFAULT_WORKER_ID, type=int)
    device_mapping = get_device_mapping()
    if not device_mapping:
        return {"status": "error", "message": "no eeg devices configured"}, 404
    worker_id = requested_worker_id if requested_worker_id in device_mapping else next(iter(device_mapping.keys()))
    worker = get_or_create_worker(worker_id)
    stream_id = f"{worker_id}-{time.time_ns()}"
    subscriber_queue = worker.subscribe()
    sent_count = 0
    ip = request.remote_addr  # ✅ 提前保存

    logger.info("sse connected | ip=%s worker=%s transport=%s endpoint=%s stream=%s", request.remote_addr, worker_id, worker.transport, worker.base_url or worker.port_str, stream_id)

    def event_stream():
        nonlocal sent_count
        try:
            while True:
                if not worker.is_alive():
                    yield f"data: {json.dumps(worker.status_payload(status='error'), ensure_ascii=False)}\n\n"
                    remove_worker_if_current(worker_id, worker)
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
    logger.info("EEG server start | config=%s", CONFIG_FILE)
    configured_devices = load_device_config()
    logger.info(
        "EEG devices loaded | count=%s devices=%s",
        len(configured_devices),
        [(device["workerId"], device.get("transport"), device.get("baseUrl") or device.get("port"), device["enabled"]) for device in configured_devices],
    )
    synchronize_workers()
    app.run(host="0.0.0.0", port=5000, threaded=True)
