import logging
from datetime import datetime

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .account import NOTIFY_ID, EsoAccount
from .config_model import build_object, imap_provider_kwargs
from .const import (
    CONF_CONSUMED,
    CONF_FOLDER,
    CONF_HOST,
    CONF_ID,
    CONF_IMAP,
    CONF_NAME,
    CONF_NOTIFY_AFTER_FAILURES,
    CONF_OBJECTS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PRICE_CURRENCY,
    CONF_PRICE_ENTITY,
    CONF_RETURNED,
    CONF_SENDER,
    CONF_SUBJECT,
    CONF_USERNAME,
    DOMAIN,
)
from .eso_client import ESOClient, TfaCodeNeeded
from .imap_client import DEFAULT_SENDER, DEFAULT_SUBJECT, ImapCodeProvider

_LOGGER = logging.getLogger(__name__)
OBJECT_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_ID): cv.string,
    vol.Required(CONF_CONSUMED, default=True): cv.boolean,
    vol.Required(CONF_RETURNED, default=False): cv.boolean,
    vol.Optional(CONF_PRICE_ENTITY): cv.string,
    vol.Optional(CONF_PRICE_CURRENCY, default="EUR"): cv.string,
})
IMAP_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=993): cv.port,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_FOLDER, default="INBOX"): cv.string,
    vol.Optional(CONF_SENDER, default=DEFAULT_SENDER): cv.string,
    vol.Optional(CONF_SUBJECT, default=DEFAULT_SUBJECT): cv.string,
})
CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_IMAP): IMAP_SCHEMA,
        vol.Optional(CONF_NOTIFY_AFTER_FAILURES, default=2): cv.positive_int,
        vol.Required(CONF_OBJECTS): cv.ensure_list(OBJECT_SCHEMA),
    })
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if DOMAIN not in config:
        return True
    conf = config[DOMAIN]
    hass.data.setdefault(DOMAIN, {})

    code_provider = None
    if CONF_IMAP in conf:
        code_provider = ImapCodeProvider(**imap_provider_kwargs(conf[CONF_IMAP]))
    client = ESOClient(
        username=conf[CONF_USERNAME],
        password=conf[CONF_PASSWORD],
        code_provider=code_provider,
    )
    account = EsoAccount(
        hass=hass,
        client=client,
        code_provider=code_provider,
        objects=[build_object(o) for o in conf[CONF_OBJECTS]],
        notify_after_failures=conf[CONF_NOTIFY_AFTER_FAILURES],
        entry=None,
    )
    hass.data[DOMAIN]["yaml"] = account

    async def async_manual_reminder(now: datetime) -> None:
        if hass.is_stopping:
            return
        account.notify(
            "Time to refresh ESO data. Call eso.start_login, then eso.submit_tfa_code "
            "with the code emailed to you.",
            "ESO data refresh due",
        )

    async def handle_start_login(call) -> None:
        try:
            needed = await hass.async_add_executor_job(account.client.start_login)
        except Exception as e:
            _LOGGER.error(f"ESO start_login error: {e}")
            account.notify(f"ESO login failed to start: {e}", "ESO login error")
            return
        if needed:
            hass.bus.async_fire("eso_tfa_required", {})
            account.notify(
                "ESO emailed you a login code. Submit it: call eso.submit_tfa_code "
                "with data code: '<the 6-digit code>'.",
                "ESO code required",
            )
        else:
            await account.async_fetch_objects(dt_util.now())
            persistent_notification.async_dismiss(hass, NOTIFY_ID)

    async def handle_submit_tfa_code(call) -> None:
        code = call.data["code"]
        try:
            await hass.async_add_executor_job(account.client.submit_code, code)
        except TfaCodeNeeded as e:
            _LOGGER.error(f"ESO submit_tfa_code rejected: {e}")
            account.notify(f"ESO code rejected: {e}", "ESO code error")
            return
        except Exception as e:
            _LOGGER.error(f"ESO submit_tfa_code error: {e}")
            account.notify(f"ESO login failed: {e}", "ESO login error")
            return
        await account.async_fetch_objects(dt_util.now())
        account.failures = 0
        persistent_notification.async_dismiss(hass, NOTIFY_ID)

    async def handle_fetch_now(call) -> None:
        if account.code_provider is None:
            account.notify(
                "eso.fetch_now needs an imap: config block (auto mode). Without it, "
                "use eso.start_login then eso.submit_tfa_code.",
                "ESO fetch_now unavailable",
            )
            return
        await account.async_login_and_fetch(dt_util.now())

    _register_services(hass, handle_fetch_now, handle_start_login, handle_submit_tfa_code)

    if code_provider is not None:
        async_track_time_change(hass, account.async_login_and_fetch, hour=5, minute=11, second=0)
    else:
        async_track_time_change(hass, async_manual_reminder, hour=5, minute=11, second=0)
    return True


def _register_services(hass, fetch_now, start_login, submit_tfa_code) -> None:
    if hass.services.has_service(DOMAIN, "fetch_now"):
        return
    hass.services.async_register(DOMAIN, "fetch_now", fetch_now)
    hass.services.async_register(DOMAIN, "start_login", start_login)
    hass.services.async_register(
        DOMAIN, "submit_tfa_code", submit_tfa_code,
        schema=vol.Schema({vol.Required("code"): cv.string}),
    )
