# custom_components/eso/entity.py
"""Shared base for ESO entities (HA-dependent; not unit-tested).

Groups the button and sensors under one device per config entry and enables
has_entity_name so each entity's friendly name is "<account> <entity name>".
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class EsoBaseEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, account, entry: ConfigEntry) -> None:
        self._account = account
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="ESO",
        )
