# -*- coding: utf-8 -*-
"""
虚拟脑电情绪模拟服务。

用途：
- 不接真实串口，直接生成可用于前端联调的脑电波形和情绪结果
- 先输出一段正常/校准状态，再平滑切换到指定情绪
- 保持与现有 `/eeg/stream` 前端消费字段基本一致

使用方式：
- 直接修改本文件顶部的 `SIMULATION_CONFIG`
- 然后运行：`python src/py/EEG_emotion_simulator.py`
"""

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from flask import Flask, Response, request


RAW_FS = 128
WINDOW_SEC = 1.0
WINDOW_SAMPLES = int(RAW_FS * WINDOW_SEC)
DEFAULT_PORT = 5001
DEFAULT_WORKER_ID = 1
EMOTIONS = ("anxiety", "stress", "fatigue", "weakness")

SIMULATION_CONFIG = {
    "emotion": "fatigue",
    "baseline_sec": 15.0,
    "transition_sec": 8.0,
    "chunk_interval": 0.5,
    "port": DEFAULT_PORT,
    "worker_id": DEFAULT_WORKER_ID,
}

EMOTION_NAMES_ZH = {
    "normal": "正常",
    "anxiety": "焦虑",
    "stress": "紧张",
    "fatigue": "疲劳",
    "weakness": "虚弱",
}

# 各情绪下的相对频段权重。这里不是医学诊断，只用于联调模拟。
BAND_PROFILES = {
    "normal": {"delta": 0.75, "theta": 0.9, "alpha": 1.2, "beta": 0.9, "gamma": 0.45},
    "anxiety": {"delta": 0.55, "theta": 0.75, "alpha": 0.7, "beta": 1.65, "gamma": 0.85},
    "stress": {"delta": 0.65, "theta": 0.7, "alpha": 0.6, "beta": 1.85, "gamma": 0.7},
    "fatigue": {"delta": 1.15, "theta": 1.55, "alpha": 1.35, "beta": 0.55, "gamma": 0.3},
    "weakness": {"delta": 1.6, "theta": 1.35, "alpha": 0.85, "beta": 0.45, "gamma": 0.22},
}


def clamp(value, low, high):
    return max(low, min(high, value))


def smoothstep(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def format_probs(target_emotion, blend):
    normal_weight = 1.0 - 0.72 * blend
    target_weight = 0.12 + 0.78 * blend
    side_weight = max(0.04, 0.14 * (1.0 - blend))

    probs = {"normal": normal_weight}
    for emotion in EMOTIONS:
        probs[emotion] = side_weight
    probs[target_emotion] = target_weight

    total = sum(probs.values())
    return {key: float(value / total) for key, value in probs.items()}


def build_indices(target_emotion, blend):
    base_scores = {
        "anxiety": 32.0,
        "stress": 35.0,
        "fatigue": 34.0,
        "weakness": 30.0,
    }
    peaks = {
        "anxiety": 84.0,
        "stress": 86.0,
        "fatigue": 82.0,
        "weakness": 80.0,
    }
    indices = {}
    for emotion in EMOTIONS:
        key = f"{emotion}_idx"
        start = base_scores[emotion]
        target = peaks[emotion] if emotion == target_emotion else start + 8.0
        indices[key] = float(np.interp(blend, [0.0, 1.0], [start, target]))
    return indices


@dataclass
class SimulatorConfig:
    emotion: str
    baseline_sec: float
    transition_sec: float
    port: int
    worker_id: int
    chunk_interval: float


class EmotionWaveSynth:
    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.start_time = time.time()
        self.queue = queue.Queue(maxsize=24)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.phase = {
            "delta": np.random.uniform(0, 2 * np.pi, size=2),
            "theta": np.random.uniform(0, 2 * np.pi, size=2),
            "alpha": np.random.uniform(0, 2 * np.pi, size=3),
            "beta": np.random.uniform(0, 2 * np.pi, size=3),
            "gamma": np.random.uniform(0, 2 * np.pi, size=2),
        }
        self.freqs = {
            "delta": np.array([1.8, 3.1]),
            "theta": np.array([4.6, 6.4]),
            "alpha": np.array([8.5, 10.1, 11.7]),
            "beta": np.array([14.2, 19.5, 24.0]),
            "gamma": np.array([31.0, 36.5]),
        }
        self.band_noise = {name: np.zeros(WINDOW_SAMPLES) for name in self.phase}
        self.amplitude_memory = {name: BAND_PROFILES["normal"][name] for name in BAND_PROFILES["normal"]}
        self.raw_buffer = deque(maxlen=WINDOW_SAMPLES * 8)
        self.sequence = 0

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def get_payload(self, timeout=1.0):
        return self.queue.get(timeout=timeout)

    def _state_blend(self, elapsed):
        baseline_end = self.config.baseline_sec
        transition_end = baseline_end + self.config.transition_sec
        if elapsed <= baseline_end:
            return "normal", 0.0, min(1.0, elapsed / max(0.1, baseline_end))
        if elapsed >= transition_end:
            return self.config.emotion, 1.0, 1.0
        progress = (elapsed - baseline_end) / max(0.1, self.config.transition_sec)
        blend = smoothstep(progress)
        return self.config.emotion, blend, 1.0

    def _mix_band_profiles(self, blend):
        normal = BAND_PROFILES["normal"]
        target = BAND_PROFILES[self.config.emotion]
        return {band: normal[band] * (1.0 - blend) + target[band] * blend for band in normal}

    def _next_band_signal(self, band, base_level):
        # 随机缓慢漂移，避免机械重复波形。
        memory = self.amplitude_memory[band]
        drift_target = base_level * np.random.uniform(0.9, 1.12)
        memory = 0.88 * memory + 0.12 * drift_target
        self.amplitude_memory[band] = memory

        t = np.arange(WINDOW_SAMPLES) / RAW_FS
        signal = np.zeros(WINDOW_SAMPLES, dtype=np.float64)
        for idx, freq in enumerate(self.freqs[band]):
            freq_jitter = freq * np.random.uniform(0.985, 1.015)
            phase = self.phase[band][idx]
            local_amp = memory * np.random.uniform(0.7, 1.25)
            signal += local_amp * np.sin(2 * np.pi * freq_jitter * t + phase)
            self.phase[band][idx] = (phase + 2 * np.pi * freq_jitter * WINDOW_SEC) % (2 * np.pi)

        noise = self.band_noise[band]
        noise = 0.94 * noise + np.random.normal(0, 0.42 * memory, WINDOW_SAMPLES)
        self.band_noise[band] = noise
        return signal + 0.18 * noise

    def _build_wave_chunk(self, band_levels):
        chunk = np.zeros(WINDOW_SAMPLES, dtype=np.float64)
        for band, level in band_levels.items():
            chunk += self._next_band_signal(band, level)

        # 叠加低频基线漂移和少量肌电噪声，增强真实感。
        t = np.arange(WINDOW_SAMPLES) / RAW_FS
        baseline_drift = 4.0 * np.sin(2 * np.pi * np.random.uniform(0.12, 0.35) * t + np.random.uniform(0, 2 * np.pi))
        muscle_noise = np.random.normal(0, 1.6, WINDOW_SAMPLES)
        chunk += baseline_drift + muscle_noise

        # 随机轻微瞬态，避免过于规则。
        if np.random.rand() < 0.22:
            center = np.random.randint(12, WINDOW_SAMPLES - 12)
            width = np.random.uniform(2.0, 7.5)
            pulse = np.exp(-0.5 * ((np.arange(WINDOW_SAMPLES) - center) / width) ** 2)
            chunk += np.random.uniform(-9.0, 9.0) * pulse

        chunk -= np.mean(chunk)
        chunk *= np.random.uniform(7.5, 11.5)
        chunk = np.clip(chunk, -180, 180)
        return chunk.astype(np.int16)

    def _build_eeg_power(self, band_levels):
        # 基于相对能量和抖动生成 8 个 TGAM 风格频段值。
        delta = 62000 * band_levels["delta"] * np.random.uniform(0.9, 1.15)
        theta = 56000 * band_levels["theta"] * np.random.uniform(0.9, 1.15)
        alpha_total = 52000 * band_levels["alpha"] * np.random.uniform(0.9, 1.12)
        beta_total = 50000 * band_levels["beta"] * np.random.uniform(0.9, 1.15)
        gamma_total = 18000 * band_levels["gamma"] * np.random.uniform(0.88, 1.2)

        low_alpha_ratio = np.random.uniform(0.45, 0.58)
        low_beta_ratio = np.random.uniform(0.46, 0.58)
        low_gamma_ratio = np.random.uniform(0.45, 0.6)

        return {
            "delta": int(delta),
            "theta": int(theta),
            "low_alpha": int(alpha_total * low_alpha_ratio),
            "high_alpha": int(alpha_total * (1.0 - low_alpha_ratio)),
            "low_beta": int(beta_total * low_beta_ratio),
            "high_beta": int(beta_total * (1.0 - low_beta_ratio)),
            "low_gamma": int(gamma_total * low_gamma_ratio),
            "mid_gamma": int(gamma_total * (1.0 - low_gamma_ratio)),
        }

    def _build_payload(self):
        elapsed = time.time() - self.start_time
        emotion, blend, calibration_progress = self._state_blend(elapsed)
        band_levels = self._mix_band_profiles(blend)
        raw_wave = self._build_wave_chunk(band_levels).tolist()
        self.raw_buffer.extend(raw_wave)
        eeg_power = self._build_eeg_power(band_levels)
        probs = format_probs(self.config.emotion, blend)
        indices = build_indices(self.config.emotion, blend)

        if blend <= 0.001:
            status = "calibrating"
            emotion_name = "normal"
            emotion_name_zh = "基线校准中"
            probs_out = {}
        else:
            status = "ok"
            emotion_name = emotion
            emotion_name_zh = EMOTION_NAMES_ZH[emotion_name]
            probs_out = probs

        self.sequence += 1
        return {
            "status": status,
            "calibration_progress": float(calibration_progress),
            "signal_quality": 0,
            "emotion": emotion_name,
            "emotion_zh": emotion_name_zh,
            "probs": probs_out,
            "indices": indices,
            "features": [],
            "workerId": self.config.worker_id,
            "port": f"SIM-{self.config.emotion.upper()}",
            "raw_powers": eeg_power,
            "raw_wave": raw_wave,
            "wave_fs": RAW_FS,
            "analysis_time": datetime.utcnow().isoformat() + "Z",
            "sequence": self.sequence,
        }

    def _run(self):
        while not self.stop_event.is_set():
            payload = self._build_payload()
            try:
                self.queue.put(payload, block=False)
            except queue.Full:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
                self.queue.put(payload, block=False)
            time.sleep(self.config.chunk_interval)


def build_app(simulator: EmotionWaveSynth):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return {
            "service": "eeg-emotion-simulator",
            "status": "ok",
            "worker_id": simulator.config.worker_id,
            "emotion": simulator.config.emotion,
            "stream_url": "/eeg/stream",
        }

    @app.get("/eeg/health")
    def health():
        return {
            "status": "ok",
            "worker_id": simulator.config.worker_id,
            "emotion": simulator.config.emotion,
            "baseline_sec": simulator.config.baseline_sec,
            "transition_sec": simulator.config.transition_sec,
        }

    @app.route("/eeg/stream")
    def stream():
        requested_worker_id = request.args.get("workerId", default=DEFAULT_WORKER_ID, type=int)
        if requested_worker_id != simulator.config.worker_id:
            return {"status": "error", "message": f"worker {requested_worker_id} unavailable"}, 404

        def event_stream():
            while True:
                try:
                    payload = simulator.get_payload(timeout=1.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    return app


def build_config_from_settings():
    emotion = SIMULATION_CONFIG.get("emotion", "fatigue")
    if emotion not in EMOTIONS:
        raise ValueError(f"emotion must be one of {EMOTIONS}, got: {emotion}")

    return SimulatorConfig(
        emotion=emotion,
        baseline_sec=max(3.0, float(SIMULATION_CONFIG.get("baseline_sec", 15.0))),
        transition_sec=max(2.0, float(SIMULATION_CONFIG.get("transition_sec", 8.0))),
        port=int(SIMULATION_CONFIG.get("port", DEFAULT_PORT)),
        worker_id=int(SIMULATION_CONFIG.get("worker_id", DEFAULT_WORKER_ID)),
        chunk_interval=max(0.2, float(SIMULATION_CONFIG.get("chunk_interval", 0.5))),
    )


def main():
    config = build_config_from_settings()

    simulator = EmotionWaveSynth(config)
    simulator.start()
    app = build_app(simulator)
    print(
        f"EEG simulator started: emotion={config.emotion}, port={config.port}, "
        f"baseline_sec={config.baseline_sec}, transition_sec={config.transition_sec}"
    )
    app.run(host="0.0.0.0", port=config.port, threaded=True)


if __name__ == "__main__":
    main()
