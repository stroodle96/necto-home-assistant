"""Draft sensor entities for observed Necto fields."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from .entity import NectoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    seen = set()

    def add_new():
        new = set(coordinator.data) - seen
        seen.update(new)
        async_add_entities(NectoSensor(coordinator, device_id, key)
                           for device_id in new
                           for key in ("temperature", "humidity", "last_report", "event"))

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class NectoSensor(NectoEntity, SensorEntity):
    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator, device_id, key)
        self.key = key
        self._attr_name = {"temperature": "Temperature", "humidity": "Humidity",
                           "last_report": "Last report", "event": "Last event"}[key]
        self._attr_device_class = {"temperature": SensorDeviceClass.TEMPERATURE,
                                   "humidity": SensorDeviceClass.HUMIDITY,
                                   "last_report": SensorDeviceClass.TIMESTAMP}.get(key)
        if key in ("temperature", "humidity"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
        if key == "humidity":
            self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_unit_of_measurement(self):
        if self.key == "temperature":
            # Fahrenheit is the only observed unit; Celsius remains unverified.
            return UnitOfTemperature.FAHRENHEIT if self.device and self.device.temperature_unit == "f" else None
        return getattr(self, "_attr_native_unit_of_measurement", None)

    @property
    def native_value(self):
        if self.device is None:
            return None
        if self.key == "temperature" and self.device.temperature_unit != "f":
            return None
        return getattr(self.device, self.key)
