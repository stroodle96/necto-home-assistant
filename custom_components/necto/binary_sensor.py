"""Draft binary entities for independent offline and powered-off flags."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import NectoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    seen = set()

    def add_new():
        new = set(coordinator.data) - seen
        seen.update(new)
        async_add_entities(NectoBinarySensor(coordinator, device_id, key)
                           for device_id in new for key in ("offline", "powered_off"))

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class NectoBinarySensor(NectoEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator, device_id, key)
        self.key = key
        self._attr_name = {"offline": "Offline", "powered_off": "Powered off"}[key]

    @property
    def is_on(self):
        return getattr(self.device, self.key) if self.device is not None else None
