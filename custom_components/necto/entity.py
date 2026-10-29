"""Common device identity for Necto entities."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class NectoEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, device_id, key):
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device(self):
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self):
        return super().available and self.device is not None

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, self.device_id)},
                          name=self.device.name if self.device else "Necto",
                          manufacturer="Necto")
