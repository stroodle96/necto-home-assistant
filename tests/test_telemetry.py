import importlib.util
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone

path = Path(__file__).parents[1] / "custom_components" / "necto" / "model.py"
spec = importlib.util.spec_from_file_location("necto_model_telemetry", path)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)
parse_devices = model.parse_devices


class TelemetryTests(unittest.TestCase):
    def test_device_telemetry_and_report_timestamp(self):
        payload = {"props": {"user": {"meta": {"unit": "f"}}, "devices": {"data": [{
            "id": 123, "device_id": "example", "name": "Example", "is_offline": False,
            "is_powered_off": True, "latest_report_at": "2024-01-02T03:04:05+00:00",
            "latest_report": {"temp_val": 64.5, "humi_val": 51, "event": "power off"},
        }]}}}
        device = parse_devices(payload)[0]
        self.assertEqual(device.device_id, "example")
        self.assertEqual(device.temperature, 64.5)
        self.assertEqual(device.temperature_unit, "f")
        self.assertEqual(device.humidity, 51)
        self.assertTrue(device.powered_off)
        self.assertFalse(device.offline)
        self.assertEqual(device.last_report, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def test_missing_latest_report_is_not_zero(self):
        payload = {"props": {"user": {"meta": {"unit": "f"}}, "devices": {"data": [{
            "device_id": "example", "name": "Example", "latest_report": None,
            "latest_report_at": None, "is_offline": True, "is_powered_off": False,
        }]}}}
        device = parse_devices(payload)[0]
        self.assertIsNone(device.temperature)
        self.assertIsNone(device.humidity)
        self.assertIsNone(device.last_report)

    def test_unexpected_structure_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_devices({"props": {}})


if __name__ == "__main__":
    unittest.main()
