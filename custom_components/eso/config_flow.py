# custom_components/eso/config_flow.py
"""UI config flow for the ESO integration (HA-dependent; not unit-tested)."""
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .config_model import imap_provider_kwargs
from .const import (
    CONF_FOLDER,
    CONF_HOST,
    CONF_IMAP,
    CONF_NOTIFY_AFTER_FAILURES,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SENDER,
    CONF_SUBJECT,
    CONF_USERNAME,
    DEFAULT_FOLDER,
    DEFAULT_NOTIFY_AFTER_FAILURES,
    DEFAULT_PORT,
    DEFAULT_SENDER,
    DEFAULT_SUBJECT,
    DOMAIN,
)
from .eso_client import ESOClient, ESOFetchError, TfaCodeNeeded
from .imap_client import ImapCodeProvider

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_NOTIFY_AFTER_FAILURES, default=DEFAULT_NOTIFY_AFTER_FAILURES): int,
        # Optional IMAP — leave host blank to use manual/reauth mode.
        vol.Optional(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional("imap_username"): str,
        vol.Optional("imap_password"): str,
        vol.Optional(CONF_FOLDER, default=DEFAULT_FOLDER): str,
        vol.Optional(CONF_SENDER, default=DEFAULT_SENDER): str,
        vol.Optional(CONF_SUBJECT, default=DEFAULT_SUBJECT): str,
    }
)

TFA_SCHEMA = vol.Schema({vol.Required("code"): str})


def _imap_block(user_input: dict) -> dict | None:
    """Build the stored IMAP block from the flat user form, or None if no host."""
    if not user_input.get(CONF_HOST):
        return None
    return {
        CONF_HOST: user_input[CONF_HOST],
        CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: user_input.get("imap_username") or user_input[CONF_USERNAME],
        CONF_PASSWORD: user_input.get("imap_password") or user_input[CONF_PASSWORD],
        CONF_FOLDER: user_input.get(CONF_FOLDER, DEFAULT_FOLDER),
        CONF_SENDER: user_input.get(CONF_SENDER, DEFAULT_SENDER),
        CONF_SUBJECT: user_input.get(CONF_SUBJECT, DEFAULT_SUBJECT),
    }


class EsoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._client: ESOClient | None = None
        self._data: dict = {}
        self._options: dict = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            imap = _imap_block(user_input)
            self._data = {
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            if imap:
                self._data[CONF_IMAP] = imap
            self._options = {
                CONF_NOTIFY_AFTER_FAILURES: user_input.get(
                    CONF_NOTIFY_AFTER_FAILURES, DEFAULT_NOTIFY_AFTER_FAILURES
                )
            }

            code_provider = (
                ImapCodeProvider(**imap_provider_kwargs(imap)) if imap else None
            )
            self._client = ESOClient(
                username=self._data[CONF_USERNAME],
                password=self._data[CONF_PASSWORD],
                code_provider=code_provider,
            )
            try:
                if code_provider is not None:
                    await self.hass.async_add_executor_job(self._client.login)
                    return self._create_entry()
                needed = await self.hass.async_add_executor_job(self._client.start_login)
                if needed:
                    return await self.async_step_tfa()
                return self._create_entry()
            except TfaCodeNeeded:
                errors["base"] = "invalid_auth"
            except ESOFetchError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during ESO setup")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_tfa(self, user_input=None) -> ConfigFlowResult:
        errors: dict = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.submit_code, user_input["code"]
                )
                return self._create_entry()
            except TfaCodeNeeded:
                errors["base"] = "invalid_code"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error submitting ESO code")
                errors["base"] = "unknown"
        return self.async_show_form(
            step_id="tfa", data_schema=TFA_SCHEMA, errors=errors
        )

    def _create_entry(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._data[CONF_USERNAME],
            data=self._data,
            options=self._options,
        )
