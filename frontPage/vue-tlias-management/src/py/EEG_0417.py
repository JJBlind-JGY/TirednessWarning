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
from scipy.signal import butter
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


class EEGWorker(threading.Thread):
    def __init__(self, worker_id, port, baud):
        super().__init__(daemon=True)
        self.worker_id = worker_id
        self.port_str = port
        self.stop_event = threading.Event()
        self.parser = TGAMParser()
        self.analyzer = EmotionAnalyzer(baseline_sec=BASELINE_SEC)
        self.raw_buffer = deque(maxlen=WINDOW_SIZE)
        self.raw_since_last = []
        self.last_signal_quality = 0
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
                    elif event_type == "eeg_power":
                        eeg_power_event = event["value"]
                        self.total_eeg_power_count += 1
                        self._debug_log_eeg_power(eeg_power_event)

                if eeg_power_event is not None:
                    result = self.analyzer.analyze(eeg_power_event, self.last_signal_quality)
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
            samples = self.raw_since_last[::DOWNSAMPLE_FACTOR]
            self.raw_since_last.clear()
        else:
            samples = list(self.raw_buffer)[::DOWNSAMPLE_FACTOR]

        if len(samples) > 128:
            samples = samples[-128:]
        return samples

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
    port_mapping = get_port_mapping()
    if not port_mapping:
        return {"status": "error", "message": "no eeg devices configured"}, 404
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
