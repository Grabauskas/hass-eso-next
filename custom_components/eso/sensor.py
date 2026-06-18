# custom_components/eso/sensor.py
"""Last-fetch sensors for UI-configured ESO accounts (HA-dependent; not unit-tested)."""
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE
from .entity import EsoBaseEntity

STATUS_OPTIONS = ["success", "failed", "unknown"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    account = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EsoLastFetchSensor(account, entry),
            EsoStatusSensor(account, entry),
        ]
    )


class _EsoSensorBase(EsoBaseEntity, RestoreSensor):
    """Common dispatcher subscription for the ESO sensors."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self._entry.entry_id),
                self.async_write_ha_state,
            )
        )


class EsoLastFetchSensor(_EsoSensorBase):
    _attr_translation_key = "last_fetch"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, account, entry: ConfigEntry) -> None:
        super().__init__(account, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_fetch"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the last timestamp if no fetch has run since startup.
        if self._account.last_fetch_time is None:
            last = await self.async_get_last_sensor_data()
            if last is not None and last.native_value is not None:
                self._account.last_fetch_time = last.native_value

    @property
    def native_value(self):
        return self._account.last_fetch_time


class EsoStatusSensor(_EsoSensorBase):
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, account, entry: ConfigEntry) -> None:
        super().__init__(account, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the last status value if no fetch has run since startup.
        # The error attribute is transient and is not restored.
        if self._account.last_fetch_status is None:
            last = await self.async_get_last_sensor_data()
            if last is not None and last.native_value in ("success", "failed"):
                self._account.last_fetch_status = last.native_value

    @property
    def native_value(self):
        return self._account.last_fetch_status or "unknown"

    @property
    def extra_state_attributes(self):
        return {"error": self._account.last_fetch_error}
