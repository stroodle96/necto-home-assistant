"""Draft sensor entities for observed Necto fields."""

from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .entity import NectoEntity

PARALLEL_UPDATES = 0
MAX_REPORT_AGE = timedelta(hours=1)


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
        self._cancel_freshness_timer = None
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
    def available(self):
        if self.key in ("temperature", "humidity"):
            report = self._report_time()
            if report is None:
                return False
            now = dt_util.utcnow()
            return report <= now < report + MAX_REPORT_AGE
        return super().available

    def _report_time(self):
        """Return a valid UTC report time, or None for unusable timestamps."""
        device = self.device
        report = device.last_report if device is not None else None
        if not isinstance(report, datetime) or report.tzinfo is None:
            return None
        try:
            if report.utcoffset() is None:
                return None
            report = report.astimezone(timezone.utc)
            report + MAX_REPORT_AGE  # Reject dates that would overflow.
        except (OverflowError, ValueError):
            return None
        return report

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._schedule_freshness_timer()

    async def async_will_remove_from_hass(self):
        self._cancel_timer()
        await super().async_will_remove_from_hass()

    @callback
    def _cancel_timer(self):
        if self._cancel_freshness_timer is not None:
            self._cancel_freshness_timer()
            self._cancel_freshness_timer = None

    @callback
    def _schedule_freshness_timer(self):
        self._cancel_timer()
        if self.key not in ("temperature", "humidity"):
            return
        report = self._report_time()
        if report is None:
            return
        now = dt_util.utcnow()
        transition = report if report > now else report + MAX_REPORT_AGE
        if transition > now:
            self._cancel_freshness_timer = async_track_point_in_utc_time(
                self.hass, self._freshness_changed, transition
            )

    @callback
    def _freshness_changed(self, _now):
        self._cancel_freshness_timer = None
        self._schedule_freshness_timer()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        self._schedule_freshness_timer()
        super()._handle_coordinator_update()

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
