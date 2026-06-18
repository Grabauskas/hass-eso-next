# custom_components/eso/button.py
"""Fetch-now button for UI-configured ESO accounts (HA-dependent; not unit-tested)."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import EsoBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    account = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EsoFetchButton(account, entry)])


class EsoFetchButton(EsoBaseEntity, ButtonEntity):
    _attr_translation_key = "fetch"

    def __init__(self, account, entry: ConfigEntry) -> None:
        super().__init__(account, entry)
        self._attr_unique_id = f"{entry.entry_id}_fetch"

    async def async_press(self) -> None:
        # Auto mode (IMAP) fetches immediately; manual mode starts the reauth
        # flow so the user enters the freshly emailed code from the UI.
        await self._account.async_login_and_fetch(dt_util.now())
