"""Behavior tests with lightweight Home Assistant API stubs, not a HA runtime."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest


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

    @property
    def available(self):
        return self.coordinator.last_update_success


module("custom_components")
package = module("custom_components.necto")
package.__path__ = [str(ROOT)]
module("homeassistant")
module("homeassistant.helpers")
module("homeassistant.helpers.device_registry", DeviceInfo=lambda **kwargs: kwargs)
module("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity)
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
        self.device = SimpleNamespace(name="Example", temperature=42.0, temperature_unit="f",
                                      humidity=48, last_report=None, event="power off",
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
