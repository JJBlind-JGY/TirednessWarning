import importlib.util
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "EEG_0417.py"
SPEC = importlib.util.spec_from_file_location("eeg_wifi_service", MODULE_PATH)
EEG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EEG
SPEC.loader.exec_module(EEG)


def payload(start, samples, *, next_index=None, boot_id="boot-1", summary_index=1):
    end = start + len(samples)
    return {
        "schemaVersion": 1,
        "deviceId": "test-device",
        "bootId": boot_id,
        "sampleRateHz": 512,
        "firstAvailableIndex": 0,
        "startIndex": start,
        "returnedUntilIndex": end,
        "nextSampleIndex": end if next_index is None else next_index,
        "overflow": False,
        "summaryIndex": summary_index,
        "poorSignal": 0,
        "attention": 55,
        "meditation": 45,
        "rssi": -48,
        "validPackets": 10,
        "checksumErrors": 0,
        "bands": {
            "delta": 100,
            "theta": 200,
            "lowAlpha": 300,
            "highAlpha": 400,
            "lowBeta": 500,
            "highBeta": 600,
            "lowGamma": 700,
            "midGamma": 800,
        },
        "samples": samples,
    }


def tgam_packet(payload_bytes):
    checksum = (~sum(payload_bytes)) & 0xFF
    return bytes([0xAA, 0xAA, len(payload_bytes), *payload_bytes, checksum])


def raw_payload(value):
    if value < 0:
        value = (1 << 16) + value
    return [0x80, 0x02, (value >> 8) & 0xFF, value & 0xFF]


def power_payload(values):
    payload_bytes = [0x83, 0x18]
    for value in values:
        payload_bytes.extend([(value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])
    return payload_bytes


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.is_open = True

    def read(self, _size):
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.01)
        return b""

    def close(self):
        self.is_open = False


class FakeDeviceHandler(BaseHTTPRequestHandler):
    response_payload = payload(0, [1, 2, 3])

    def do_GET(self):
        body = json.dumps(self.response_payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class WifiEegWorkerTests(unittest.TestCase):
    def make_worker(self):
        return EEG.EEGWorker(1, "http://127.0.0.1:1")

    def test_incremental_samples_are_deduplicated(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [10, 11, 12]), 10_000)
        worker._consume_samples(payload(1, [11, 12, 13]), 10_100)
        self.assertEqual([item["value"] for item in worker.raw_tgam_history], [10, 11, 12, 13])
        self.assertEqual(worker.sample_cursor, 4)

    def test_gap_is_counted_and_resets_partial_window(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [1, 2]), 10_000)
        worker._consume_samples(payload(5, [6, 7]), 10_100)
        self.assertEqual(worker.dropped_sample_count, 3)
        self.assertEqual(list(worker.raw_buffer), [6, 7])
        self.assertEqual(worker.analyzer.baseline_reset_reason, "sample_gap")

    def test_sample_timestamps_follow_512_hz_order(self):
        worker = self.make_worker()
        worker._consume_samples(payload(100, [1, 2, 3], next_index=103), 20_000)
        timestamps = [item["ts"] for item in worker.raw_tgam_history]
        self.assertEqual(timestamps[-1], 20_000)
        self.assertLess(timestamps[0], timestamps[1])
        self.assertLess(timestamps[1], timestamps[2])

    def test_http_fetch_validates_real_wire_shape(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDeviceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            worker = EEG.EEGWorker(1, f"http://127.0.0.1:{server.server_port}")
            result = worker._fetch_payload()
            worker._validate_payload(result)
            self.assertEqual(result["deviceId"], "test-device")
            self.assertEqual(result["samples"], [1, 2, 3])
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_device_url_is_rejected(self):
        with self.assertRaises(ValueError):
            EEG.normalize_device({"workerId": 1, "name": "bad", "baseUrl": "COM5"})

    def test_serial_device_config_is_normalized(self):
        device = EEG.normalize_device({"workerId": 2, "name": "serial", "transport": "serial", "port": "COM5"})
        self.assertEqual(device["transport"], "serial")
        self.assertEqual(device["port"], "COM5")
        self.assertEqual(device["baud"], 57600)
        self.assertEqual(device["baseUrl"], "")

    def test_legacy_serial_config_is_normalized(self):
        device = EEG.normalize_device({"workerId": 2, "name": "serial", "port": "COM5"})
        self.assertEqual(device["transport"], "serial")
        self.assertEqual(device["label"], "serial / COM5 / 57600")

    def test_legacy_wifi_config_is_normalized(self):
        device = EEG.normalize_device({"workerId": 1, "name": "wifi", "baseUrl": "10.137.178.196"})
        self.assertEqual(device["transport"], "wifi")
        self.assertEqual(device["baseUrl"], "http://10.137.178.196")

    def test_bare_ip_is_normalized_to_http(self):
        device = EEG.normalize_device({
            "workerId": 1,
            "name": "helmet",
            "baseUrl": "10.137.178.196",
        })
        self.assertEqual(device["baseUrl"], "http://10.137.178.196")

    def test_transport_reset_clears_partial_data_on_device_restart(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [1, 2, 3]), 10_000)
        worker.device_boot_id = "old-boot"
        worker._reset_transport_state("device_restarted")
        worker.sample_cursor = 0
        self.assertEqual(list(worker.raw_buffer), [])
        self.assertEqual(worker.raw_since_last, [])
        self.assertEqual(worker.analyzer.baseline_reset_reason, "device_restarted")

    def test_multiple_workers_keep_independent_cursors(self):
        first = EEG.EEGWorker(1, "http://127.0.0.1:1")
        second = EEG.EEGWorker(2, "http://127.0.0.1:2")
        first._consume_samples(payload(0, [1, 2]), 10_000)
        second._consume_samples(payload(50, [8, 9, 10]), 10_000)
        self.assertEqual(first.sample_cursor, 2)
        self.assertEqual(second.sample_cursor, 53)
        self.assertEqual(first.total_raw_count, 2)
        self.assertEqual(second.total_raw_count, 3)

    def test_snapshot_contains_reconstructed_raw_samples(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [3, 4, 5, 6]), 20_000)
        result = worker.snapshot(seconds=1, before_ms=20_000)
        self.assertEqual(result["rawTgamSamples"], [3, 4, 5, 6])
        self.assertEqual(result["rawTgamCount"], 4)
        self.assertEqual(result["rawWaveOriginal"], [3, 4, 5, 6])
        self.assertEqual(result["rawWaveOriginalFs"], 512)

    def test_analysis_payload_keeps_original_wave_for_display(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [101, -202, 303]), 20_000)
        result = worker._build_analysis_payload(payload(0, [], summary_index=2))
        self.assertEqual(result["raw_wave_original"], [101, -202, 303])
        self.assertEqual(result["raw_wave_original_fs"], 512)
        self.assertTrue(result["raw_wave_original_live_published"])
        self.assertIn("raw_wave", result)
        self.assertIn("raw_wave_display", result)
        self.assertEqual(result["display_wave_fs"], 128)

    def test_display_filter_removes_constant_offset(self):
        worker = self.make_worker()
        samples = [1200] * (EEG.RAW_FS * 2)
        filtered = np.asarray(worker._filter_display_samples(samples, update_state=False))
        self.assertLess(np.mean(np.abs(filtered[-EEG.RAW_FS:])), 1.0)

    def test_display_filter_suppresses_fifty_hz_noise(self):
        worker = self.make_worker()
        timeline = np.arange(EEG.RAW_FS * 4) / EEG.RAW_FS
        samples = 300 * np.sin(2 * np.pi * 10 * timeline) + 300 * np.sin(2 * np.pi * 50 * timeline)
        filtered = np.asarray(worker._filter_display_samples(samples, update_state=False))
        frequencies = np.fft.rfftfreq(filtered.size, 1 / EEG.RAW_FS)
        spectrum = np.abs(np.fft.rfft(filtered))
        power_10 = spectrum[np.argmin(np.abs(frequencies - 10))]
        power_50 = spectrum[np.argmin(np.abs(frequencies - 50))]
        self.assertGreater(power_10, power_50 * 8)

    def test_display_filter_preserves_action_amplitude_change(self):
        worker = self.make_worker()
        timeline = np.arange(EEG.RAW_FS * 4) / EEG.RAW_FS
        samples = 40 * np.sin(2 * np.pi * 10 * timeline)
        samples[EEG.RAW_FS * 2:] *= 5
        filtered = np.asarray(worker._filter_display_samples(samples, update_state=False))
        quiet_rms = np.sqrt(np.mean(filtered[EEG.RAW_FS:EEG.RAW_FS * 2] ** 2))
        action_rms = np.sqrt(np.mean(filtered[EEG.RAW_FS * 3:] ** 2))
        self.assertGreater(action_rms, quiet_rms * 3)

    def test_consume_samples_returns_only_new_original_values(self):
        worker = self.make_worker()
        _, first = worker._consume_samples(payload(0, [10, 11, 12]), 10_000)
        _, second = worker._consume_samples(payload(1, [11, 12, 13]), 10_100)
        self.assertEqual(first, [10, 11, 12])
        self.assertEqual(second, [13])

    def test_no_contact_advances_cursor_without_buffering_wave(self):
        worker = self.make_worker()
        no_contact = payload(0, [10, 11, 12])
        no_contact["poorSignal"] = 200
        _, blocked, status, quality = worker._update_contact_state(no_contact["poorSignal"])
        _, accepted = worker._consume_samples(no_contact, 10_000, accept_samples=not blocked)
        self.assertTrue(blocked)
        self.assertEqual(status, "no_contact")
        self.assertEqual(quality, "no_contact")
        self.assertEqual(accepted, [])
        self.assertEqual(worker.sample_cursor, 3)
        self.assertEqual(list(worker.raw_buffer), [])
        self.assertEqual(list(worker.raw_tgam_history), [])

    def test_poor_signal_clears_existing_wave(self):
        worker = self.make_worker()
        worker._consume_samples(payload(0, [1, 2, 3]), 10_000)
        worker._filter_display_samples([1] * 64)
        changed, blocked, status, quality = worker._update_contact_state(107)
        self.assertTrue(changed)
        self.assertTrue(blocked)
        self.assertEqual(status, "poor_signal")
        self.assertEqual(quality, "bad_contact")
        self.assertEqual(list(worker.raw_buffer), [])
        self.assertEqual(worker.raw_since_last, [])
        self.assertIsNone(worker.display_filter_zi)

    def test_contact_recovery_only_accepts_new_samples(self):
        worker = self.make_worker()
        blocked_payload = payload(0, [1, 2, 3])
        blocked_payload["poorSignal"] = 200
        worker._update_contact_state(200)
        worker._consume_samples(blocked_payload, 10_000, accept_samples=False)
        changed, blocked, _, quality = worker._update_contact_state(0)
        recovered_payload = payload(3, [4, 5])
        _, accepted = worker._consume_samples(recovered_payload, 10_100, accept_samples=not blocked)
        self.assertTrue(changed)
        self.assertFalse(blocked)
        self.assertEqual(quality, "good")
        self.assertEqual(accepted, [4, 5])
        self.assertEqual(list(worker.raw_buffer), [4, 5])

    def test_serial_worker_parses_tgam_stream(self):
        samples = tgam_packet(raw_payload(101)) + tgam_packet([0x02, 0, 0x04, 55, 0x05, 45]) + tgam_packet(power_payload([100, 200, 300, 400, 500, 600, 700, 800]))
        worker = EEG.SerialEEGWorker(4, "COM_TEST")
        worker.ser = FakeSerial([samples])
        published = []
        worker._publish = published.append
        worker._open_serial = lambda: worker._set_status("online")
        worker.stop_event.wait = lambda _timeout=None: False

        original_sleep = time.sleep
        try:
            time.sleep = lambda _seconds: worker.stop_event.set()
            worker.run()
        finally:
            time.sleep = original_sleep

        analysis = [item for item in published if item.get("raw_powers")]
        self.assertTrue(analysis)
        self.assertEqual(analysis[-1]["transport"], "serial")
        self.assertEqual(analysis[-1]["port"], "COM_TEST")
        self.assertEqual(analysis[-1]["raw_powers"]["low_alpha"], 300)
        self.assertEqual(worker.total_raw_count, 1)
        self.assertEqual(worker.total_eeg_power_count, 1)

    def test_synchronize_workers_starts_all_enabled_devices(self):
        devices = [
            {"workerId": 1, "value": 1, "name": "one", "baseUrl": "http://127.0.0.1:1", "enabled": True},
            {"workerId": 2, "value": 2, "name": "two", "transport": "serial", "port": "COM2", "baud": 57600, "enabled": True},
            {"workerId": 3, "value": 3, "name": "disabled", "baseUrl": "http://127.0.0.1:3", "enabled": False},
        ]
        original_workers = EEG.workers
        EEG.workers = EEG.OrderedDict()
        try:
            with patch.object(EEG, "load_device_config", return_value=devices):
                mapping = EEG.synchronize_workers()
            time.sleep(0.05)
            self.assertEqual(set(mapping), {1, 2})
            self.assertEqual(set(EEG.workers), {1, 2})
            self.assertEqual(EEG.workers[1].transport, "wifi")
            self.assertEqual(EEG.workers[2].transport, "serial")
        finally:
            for worker in EEG.workers.values():
                worker.stop()
                worker.join(timeout=1)
            EEG.workers = original_workers


if __name__ == "__main__":
    unittest.main()
