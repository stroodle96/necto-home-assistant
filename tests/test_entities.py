"""Behavior tests with lightweight Home Assistant API stubs, not a HA runtime."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


ROOT = Path(__file__).parents[1] / "custom_components" / "necto"


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = object()
        self.writes = 0

    async def async_added_to_hass(self):
        pass

    async def async_will_remove_from_hass(self):
        pass

    def async_write_ha_state(self):
        self.writes += 1

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    @property
    def available(self):
        return self.coordinator.last_update_success


module("custom_components")
package = module("custom_components.necto")
package.__path__ = [str(ROOT)]
module("homeassistant")
module("homeassistant.core", callback=lambda f: f)
module("homeassistant.helpers")
module("homeassistant.helpers.event", async_track_point_in_utc_time=lambda *args: lambda: None)
module("homeassistant.helpers.device_registry", DeviceInfo=lambda **kwargs: kwargs)
module("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity)
module("homeassistant.util")
module("homeassistant.util.dt", utcnow=lambda: datetime.now(timezone.utc))
module("homeassistant.components")
module("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (), {}),
       SensorDeviceClass=SimpleNamespace(TEMPERATURE="temperature", HUMIDITY="humidity", TIMESTAMP="timestamp"),
       SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"))
module("homeassistant.components.binary_sensor", BinarySensorEntity=type("BinarySensorEntity", (), {}),
       BinarySensorDeviceClass=SimpleNamespace(PROBLEM="problem"))
module("homeassistant.const", PERCENTAGE="%", UnitOfTemperature=SimpleNamespace(FAHRENHEIT="°F"))
load("custom_components.necto.const", "const.py")
load("custom_components.necto.entity", "entity.py")
sensor = load("custom_components.necto.sensor", "sensor.py")
binary_sensor = load("custom_components.necto.binary_sensor", "binary_sensor.py")


class EntityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
        self.device = SimpleNamespace(name="Example", temperature=42.0, temperature_unit="f",
                                      humidity=48, last_report=self.now, event="power off",
                                      offline=False, powered_off=True)
        self.coordinator = SimpleNamespace(data={"example": self.device}, last_update_success=True)

    def test_temperature_and_unverified_unit(self):
        entity = sensor.NectoSensor(self.coordinator, "example", "temperature")
        self.assertEqual(entity.native_value, 42.0)
        self.assertEqual(entity.native_unit_of_measurement, "°F")
        self.device.temperature_unit = "c"
        self.assertIsNone(entity.native_value)

    def test_offline_and_power_off_are_independent(self):
        offline = binary_sensor.NectoBinarySensor(self.coordinator, "example", "offline")
        powered_off = binary_sensor.NectoBinarySensor(self.coordinator, "example", "powered_off")
        self.assertFalse(offline.is_on)
        self.assertTrue(powered_off.is_on)

    def test_removed_device_is_unavailable(self):
        entity = sensor.NectoSensor(self.coordinator, "example", "humidity")
        self.coordinator.data.clear()
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)

    def test_fresh_measurements_ignore_device_flags_and_poll_failures(self):
        with patch.object(sensor.dt_util, "utcnow", return_value=self.now):
            self.device.last_report = self.now - timedelta(minutes=59, seconds=59)
            self.device.offline = self.device.powered_off = True
            self.coordinator.last_update_success = False
            for key in ("temperature", "humidity"):
                self.assertTrue(sensor.NectoSensor(self.coordinator, "example", key).available)

    def test_exact_expiry_and_invalid_or_future_dates(self):
        entity = sensor.NectoSensor(self.coordinator, "example", "temperature")
        with patch.object(sensor.dt_util, "utcnow", return_value=self.now):
            for report, expected in ((self.now - timedelta(minutes=59, seconds=59), True),
                    (self.now - timedelta(hours=1) + timedelta(microseconds=1), True),
                    (self.now - timedelta(hours=1), False), (self.now - timedelta(hours=2), False),
                    (None, False), ("invalid", False), (datetime(2025, 1, 1), False),
                    (self.now + timedelta(seconds=1), False),
                    (datetime.max.replace(tzinfo=timezone.utc), False),
                    (self.now.astimezone(timezone(timedelta(hours=-5))), True)):
                self.device.last_report = report
                with self.subTest(report=report):
                    self.assertEqual(entity.available, expected)

    def test_diagnostics_remain_available_for_old_reports(self):
        self.device.last_report = self.now - timedelta(hours=4)
        with patch.object(sensor.dt_util, "utcnow", return_value=self.now):
            for key in ("temperature", "humidity"):
                self.assertFalse(sensor.NectoSensor(self.coordinator, "example", key).available)
            for key in ("last_report", "event"):
                self.assertTrue(sensor.NectoSensor(self.coordinator, "example", key).available)
            for key in ("offline", "powered_off"):
                self.assertTrue(binary_sensor.NectoBinarySensor(self.coordinator, "example", key).available)

    def test_expiry_timer_updates_without_poll_and_is_cancelled_on_removal(self):
        now = [self.now]
        timers = []
        def schedule(hass, callback, when):
            timer = {"callback": callback, "when": when, "cancelled": False}
            timers.append(timer)
            return lambda: timer.update(cancelled=True)
        entity = sensor.NectoSensor(self.coordinator, "example", "temperature")
        def run(coro):
            try:
                coro.send(None)
            except StopIteration:
                return
            self.fail("Unexpected async suspension")
        with patch.object(sensor.dt_util, "utcnow", side_effect=lambda: now[0]), patch.object(sensor, "async_track_point_in_utc_time", side_effect=schedule):
            run(entity.async_added_to_hass())
            self.assertEqual(timers[-1]["when"], self.now + timedelta(hours=1))
            now[0] += timedelta(hours=1)
            timers[-1]["callback"](now[0])
            self.assertFalse(entity.available)
            self.assertEqual(entity.writes, 1)
            self.device.last_report = now[0]
            entity._handle_coordinator_update()
            self.assertTrue(entity.available)
            pending = timers[-1]
            run(entity.async_will_remove_from_hass())
            self.assertTrue(pending["cancelled"])

    def test_future_report_waits_until_its_time_and_replaces_old_timer(self):
        now = [self.now]
        timers = []
        def schedule(hass, callback, when):
            timer = {"callback": callback, "when": when, "cancelled": False}
            timers.append(timer)
            return lambda: timer.update(cancelled=True)
        entity = sensor.NectoSensor(self.coordinator, "example", "humidity")
        with patch.object(sensor.dt_util, "utcnow", side_effect=lambda: now[0]), patch.object(sensor, "async_track_point_in_utc_time", side_effect=schedule):
            self.device.last_report = self.now + timedelta(minutes=1)
            entity._handle_coordinator_update()
            old = timers[-1]
            self.device.last_report = self.now + timedelta(minutes=2)
            entity._handle_coordinator_update()
            self.assertTrue(old["cancelled"])
            self.assertFalse(entity.available)
            now[0] = self.device.last_report
            timers[-1]["callback"](now[0])
            self.assertTrue(entity.available)
            self.assertEqual(timers[-1]["when"], now[0] + timedelta(hours=1))
