# custom_components/eso/config_flow.py
"""UI config flow for the ESO integration (HA-dependent; not unit-tested)."""
import logging

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .config_model import imap_block, imap_provider_kwargs, object_id_in_use
from .const import (
    CONF_CODE,
    CONF_CONSUMED,
    CONF_FOLDER,
    CONF_HOST,
    CONF_ID,
    CONF_IMAP,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USERNAME,
    CONF_NAME,
    CONF_NOTIFY_AFTER_FAILURES,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PRICE_CURRENCY,
    CONF_PRICE_ENTITY,
    CONF_RETURNED,
    CONF_SENDER,
    CONF_SUBJECT,
    CONF_USERNAME,
    DEFAULT_FOLDER,
    DEFAULT_NOTIFY_AFTER_FAILURES,
    DEFAULT_PORT,
    DEFAULT_PRICE_CURRENCY,
    DEFAULT_SENDER,
    DEFAULT_SUBJECT,
    DOMAIN,
)
from .eso_client import ESOClient, ESOFetchError, TfaCodeNeeded, TfaSessionExpired
from .imap_client import ImapAuthError, ImapCodeProvider, ImapConnectError, TfaTimeout

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_NOTIFY_AFTER_FAILURES, default=DEFAULT_NOTIFY_AFTER_FAILURES): int,
        # Optional IMAP — leave host blank to use manual/reauth mode.
        vol.Optional(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_IMAP_USERNAME): str,
        vol.Optional(CONF_IMAP_PASSWORD): str,
        vol.Optional(CONF_FOLDER, default=DEFAULT_FOLDER): str,
        vol.Optional(CONF_SENDER, default=DEFAULT_SENDER): str,
        vol.Optional(CONF_SUBJECT, default=DEFAULT_SUBJECT): str,
    }
)

TFA_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


class EsoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry):
        return {"object": EsoObjectSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "EsoOptionsFlow":
        return EsoOptionsFlow()

    def __init__(self) -> None:
        self._client: ESOClient | None = None
        self._data: dict = {}
        self._options: dict = {}
        self._reauth_password: str | None = None
        self._login_task = None
        self._progress_error: str | None = None

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            imap = imap_block(user_input)
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
                # Fast credential POST only — never block here. If a code is
                # needed and IMAP is configured, verify the mailbox is reachable
                # *before* committing to a long poll, so a bad host/credentials
                # fail fast with a clear message instead of a silent spinner.
                needed = await self.hass.async_add_executor_job(self._client.start_login)
                if needed and code_provider is not None:
                    await self.hass.async_add_executor_job(code_provider.check_connection)
            except ImapConnectError:
                errors["base"] = "imap_unreachable"
            except ImapAuthError:
                errors["base"] = "imap_auth"
            except ESOFetchError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during ESO setup")
                errors["base"] = "unknown"
            else:
                if not needed:
                    # No TFA challenge. Success only if we actually reached the
                    # consumption page; otherwise ESO rejected the credentials
                    # (it re-rendered the login page) and we must not create an
                    # entry.
                    if self._client.is_authenticated():
                        return await self.async_step_object()
                    errors["base"] = "invalid_auth"
                elif code_provider is None:
                    return await self.async_step_tfa()
                else:
                    # Auto mode: fetch the emailed code in the background so the
                    # user sees a real "waiting for the code" progress step.
                    return await self.async_step_wait_code()

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_wait_code(self, user_input=None) -> ConfigFlowResult:
        """Progress step: poll IMAP for the emailed code and submit it.

        Runs finish_login() (the blocking wait + submit) as a background task so
        the frontend shows a progress indicator instead of a featureless spinner.
        """
        if self._login_task is None:
            self._login_task = self.hass.async_create_task(self._async_wait_for_code())
            return self.async_show_progress(
                step_id="wait_code",
                progress_action="wait_code",
                progress_task=self._login_task,
            )
        error = self._login_task.result()
        self._login_task = None
        if error:
            self._progress_error = error
            return self.async_show_progress_done(next_step_id="wait_code_failed")
        return self.async_show_progress_done(next_step_id="finish")

    async def _async_wait_for_code(self) -> str | None:
        """Wait for the IMAP code and submit it. Returns an error key, or None on
        success. Run inside a background task by async_step_wait_code."""
        try:
            await self.hass.async_add_executor_job(self._client.finish_login)
        except TfaTimeout:
            return "code_timeout"
        except ImapConnectError:
            return "imap_unreachable"
        except ImapAuthError:
            return "imap_auth"
        except TfaCodeNeeded:
            return "invalid_code"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error waiting for the ESO code")
            return "unknown"
        if not self._client.is_authenticated():
            return "invalid_auth"
        return None

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        """After a successful background login, collect the first object."""
        return await self.async_step_object()

    async def async_step_wait_code_failed(self, user_input=None) -> ConfigFlowResult:
        """Re-display the credentials form with the error from the background
        login, so the user can correct input and retry."""
        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors={"base": self._progress_error or "unknown"},
        )

    async def async_step_tfa(self, user_input=None) -> ConfigFlowResult:
        errors: dict = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.submit_code, user_input[CONF_CODE]
                )
                return await self.async_step_object()
            except TfaSessionExpired:
                # Window lapsed / no pending challenge: mint a fresh one so the
                # user can enter the newly emailed code instead of being stuck.
                errors["base"] = await self._remint_code()
            except TfaCodeNeeded:
                errors["base"] = "invalid_code"
            except ESOFetchError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error submitting ESO code")
                errors["base"] = "unknown"
        return self.async_show_form(
            step_id="tfa", data_schema=TFA_SCHEMA, errors=errors
        )

    async def _remint_code(self) -> str:
        """Re-POST credentials so ESO emails a fresh code. Returns the error key
        to show on the re-displayed code form ('code_expired' on success,
        'cannot_connect' if the re-login itself failed)."""
        try:
            await self.hass.async_add_executor_job(self._client.start_login)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to mint a fresh ESO login code")
            return "cannot_connect"
        return "code_expired"

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """Confirm/refresh credentials and trigger a fresh login code.

        The password is editable here so a changed ESO password can be fixed
        without deleting the entry; it defaults to the stored one so a user who
        only needs a new code can submit unchanged.
        """
        entry = self._get_reauth_entry()
        errors: dict = {}
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            imap = entry.data.get(CONF_IMAP)
            code_provider = (
                ImapCodeProvider(**imap_provider_kwargs(imap)) if imap else None
            )
            self._client = ESOClient(
                username=entry.data[CONF_USERNAME],
                password=password,
                code_provider=code_provider,
            )
            self._reauth_password = password
            try:
                needed = await self.hass.async_add_executor_job(self._client.start_login)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("ESO reauth start_login failed")
                errors["base"] = "cannot_connect"
            else:
                if needed:
                    return await self.async_step_reauth_code()
                # No code required: only a success if we actually logged in.
                if self._client.is_authenticated():
                    return await self._finish_reauth(entry)
                errors["base"] = "invalid_auth"
        schema = vol.Schema(
            {vol.Required(CONF_PASSWORD, default=entry.data[CONF_PASSWORD]): str}
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    async def async_step_reauth_code(self, user_input=None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.submit_code, user_input[CONF_CODE]
                )
            except TfaSessionExpired:
                errors["base"] = await self._remint_code()
            except TfaCodeNeeded:
                errors["base"] = "invalid_code"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("ESO reauth submit_code failed")
                return self.async_abort(reason="reauth_failed")
            else:
                return await self._finish_reauth(entry)
        return self.async_show_form(
            step_id="reauth_code", data_schema=TFA_SCHEMA, errors=errors
        )

    async def _finish_reauth(self, entry: ConfigEntry) -> ConfigFlowResult:
        """Persist any password change, inject the authenticated client into the
        live account, fetch, then abort. Reports success only if the fetch ran."""
        data = entry.data
        if self._reauth_password and self._reauth_password != data.get(CONF_PASSWORD):
            data = {**data, CONF_PASSWORD: self._reauth_password}

        account = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if account is None:
            # Entry not currently loaded; reload so a fresh login runs with the
            # (possibly updated) credentials.
            return self.async_update_reload_and_abort(entry, data=data)
        if data is not entry.data:
            self.hass.config_entries.async_update_entry(entry, data=data)
        account.client = self._client
        try:
            await account.async_fetch_objects(dt_util.now())
        except Exception:  # noqa: BLE001
            _LOGGER.exception("ESO reauth fetch failed")
            return self.async_abort(reason="reauth_failed")
        account.failures = 0
        return self.async_abort(reason="reauth_successful")

    async def async_step_object(self, user_input=None) -> ConfigFlowResult:
        """Collect the first metering object, then create the entry with it as a
        subentry. An account with no object imports nothing, so setup requires at
        least one; further objects are added later via 'Add ESO object'."""
        errors: dict = {}
        if user_input is not None:
            error = _object_form_error(user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._data[CONF_USERNAME],
                    data=self._data,
                    options=self._options,
                    subentries=[
                        {
                            "subentry_type": "object",
                            "title": user_input[CONF_NAME],
                            "data": user_input,
                            "unique_id": None,
                        }
                    ],
                )
        return self.async_show_form(
            step_id="object", data_schema=_object_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Edit the ESO password and IMAP settings of an existing entry without
        deleting it. The username is the entry identity and stays fixed; clearing
        the IMAP host switches the account to manual code entry."""
        entry = self._get_reconfigure_entry()
        errors: dict = {}
        if user_input is not None:
            merged = {
                **user_input,
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            new_data = {
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            imap = imap_block(merged)
            if imap:
                new_data[CONF_IMAP] = imap
            return self.async_update_reload_and_abort(entry, data=new_data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(entry.data),
            errors=errors,
        )


def _object_form_error(user_input: dict) -> str | None:
    """Validate the required free-text fields of an object form. Returns the
    error key to show, or None if name and id are both non-blank. vol.Required
    accepts whitespace-only strings, which would yield a blank entry title and a
    malformed statistic id, so reject them here."""
    if not (user_input.get(CONF_NAME) or "").strip():
        return "missing_object_name"
    if not (user_input.get(CONF_ID) or "").strip():
        return "missing_object_id"
    return None


def _object_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): str,
            vol.Required(CONF_ID, default=d.get(CONF_ID, "")): str,
            vol.Required(CONF_CONSUMED, default=d.get(CONF_CONSUMED, True)): bool,
            vol.Required(CONF_RETURNED, default=d.get(CONF_RETURNED, False)): bool,
            # suggested_value (not default) so clearing the price entity on an
            # existing object actually removes it; a default would be re-applied
            # when the frontend omits the emptied field.
            vol.Optional(
                CONF_PRICE_ENTITY,
                description={"suggested_value": d.get(CONF_PRICE_ENTITY, "")},
            ): str,
            vol.Required(
                CONF_PRICE_CURRENCY,
                default=d.get(CONF_PRICE_CURRENCY, DEFAULT_PRICE_CURRENCY),
            ): str,
        }
    )


def _reconfigure_schema(data: dict) -> vol.Schema:
    """Schema for the reconfigure step, pre-filled from the stored entry data.

    Mirrors the IMAP field names of USER_SCHEMA so imap_block() can rebuild the
    stored block. The username is omitted (it is the entry identity).

    The IMAP fields pre-fill via ``suggested_value`` rather than ``default``:
    clearing the host must actually drop the field so IMAP can be removed. A
    ``default`` would be re-applied by voluptuous when the frontend omits the
    emptied field, making the IMAP block impossible to clear (the old value
    would silently come back)."""
    imap = data.get(CONF_IMAP) or {}

    def _suggest(key, value):
        return vol.Optional(key, description={"suggested_value": value})

    return vol.Schema(
        {
            vol.Required(CONF_PASSWORD, default=data[CONF_PASSWORD]): str,
            _suggest(CONF_HOST, imap.get(CONF_HOST, "")): str,
            _suggest(CONF_PORT, imap.get(CONF_PORT, DEFAULT_PORT)): int,
            _suggest(CONF_IMAP_USERNAME, imap.get(CONF_USERNAME, "")): str,
            _suggest(CONF_IMAP_PASSWORD, imap.get(CONF_PASSWORD, "")): str,
            _suggest(CONF_FOLDER, imap.get(CONF_FOLDER, DEFAULT_FOLDER)): str,
            _suggest(CONF_SENDER, imap.get(CONF_SENDER, DEFAULT_SENDER)): str,
            _suggest(CONF_SUBJECT, imap.get(CONF_SUBJECT, DEFAULT_SUBJECT)): str,
        }
    )


class EsoObjectSubentryFlow(ConfigSubentryFlow):
    """Flow for adding/editing an ESO metering point subentry."""

    def _existing_object_ids(self, exclude_subentry_id: str | None = None) -> list[str]:
        return [
            sub.data.get(CONF_ID, "")
            for sub in self._get_entry().subentries.values()
            if sub.subentry_type == "object" and sub.subentry_id != exclude_subentry_id
        ]

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        errors: dict = {}
        if user_input is not None:
            error = _object_form_error(user_input)
            if error:
                errors["base"] = error
            elif object_id_in_use(self._existing_object_ids(), user_input[CONF_ID]):
                errors["base"] = "duplicate_object"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_object_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict = {}
        if user_input is not None:
            others = self._existing_object_ids(exclude_subentry_id=subentry.subentry_id)
            error = _object_form_error(user_input)
            if error:
                errors["base"] = error
            elif object_id_in_use(others, user_input[CONF_ID]):
                errors["base"] = "duplicate_object"
            else:
                return self.async_update_and_abort(
                    self._get_entry(), subentry,
                    title=user_input[CONF_NAME], data=user_input,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_object_schema(user_input or subentry.data),
            errors=errors,
        )


class EsoOptionsFlow(OptionsFlow):
    """Options flow letting the user edit notify_after_failures after setup."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_NOTIFY_AFTER_FAILURES, DEFAULT_NOTIFY_AFTER_FAILURES
        )
        schema = vol.Schema(
            {vol.Required(CONF_NOTIFY_AFTER_FAILURES, default=current): int}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
