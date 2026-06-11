import importlib.util
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


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

    def test_synchronize_workers_starts_all_enabled_devices(self):
        devices = [
            {"workerId": 1, "value": 1, "name": "one", "baseUrl": "http://127.0.0.1:1", "enabled": True},
            {"workerId": 2, "value": 2, "name": "two", "baseUrl": "http://127.0.0.1:2", "enabled": True},
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
            self.assertTrue(all(worker.is_alive() for worker in EEG.workers.values()))
        finally:
            for worker in EEG.workers.values():
                worker.stop()
                worker.join(timeout=1)
            EEG.workers = original_workers


if __name__ == "__main__":
    unittest.main()
