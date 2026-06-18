import logging
from datetime import datetime

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
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
    DEFAULT_NOTIFY_AFTER_FAILURES,
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


def _ensure_services(hass: HomeAssistant) -> None:
    """Register all ESO services once; subsequent calls are no-ops."""
    if hass.services.has_service(DOMAIN, "fetch_now"):
        return

    async def handle_fetch_now(call) -> None:
        accounts = list(hass.data.get(DOMAIN, {}).values())
        ran = False
        for account in accounts:
            if getattr(account, "code_provider", None) is None:
                continue
            await account.async_login_and_fetch(dt_util.now())
            ran = True
        if not ran:
            persistent_notification.async_create(
                hass,
                "eso.fetch_now needs an IMAP-configured account (auto mode).",
                title="ESO fetch_now unavailable",
                notification_id=NOTIFY_ID,
            )

    async def handle_start_login(call) -> None:
        account = hass.data.get(DOMAIN, {}).get("yaml")
        if account is None:
            return
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
        account = hass.data.get(DOMAIN, {}).get("yaml")
        if account is None:
            return
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

    hass.services.async_register(DOMAIN, "fetch_now", handle_fetch_now)
    hass.services.async_register(DOMAIN, "start_login", handle_start_login)
    hass.services.async_register(
        DOMAIN, "submit_tfa_code", handle_submit_tfa_code,
        schema=vol.Schema({vol.Required("code"): cv.string}),
    )


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

    _ensure_services(hass)

    if code_provider is not None:
        async_track_time_change(hass, account.async_login_and_fetch, hour=5, minute=11, second=0)
    else:
        async_track_time_change(hass, async_manual_reminder, hour=5, minute=11, second=0)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    data = entry.data
    code_provider = None
    if data.get(CONF_IMAP):
        code_provider = ImapCodeProvider(**imap_provider_kwargs(data[CONF_IMAP]))
    client = ESOClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        code_provider=code_provider,
    )
    objects = [
        build_object(sub.data)
        for sub in entry.subentries.values()
        if sub.subentry_type == "object"
    ]
    account = EsoAccount(
        hass=hass,
        client=client,
        code_provider=code_provider,
        objects=objects,
        notify_after_failures=entry.options.get(
            CONF_NOTIFY_AFTER_FAILURES, DEFAULT_NOTIFY_AFTER_FAILURES
        ),
        entry=entry,
    )
    hass.data[DOMAIN][entry.entry_id] = account

    _ensure_services(hass)

    account.unsub = async_track_time_change(
        hass, account.async_login_and_fetch, hour=5, minute=11, second=0
    )
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    account = hass.data[DOMAIN].pop(entry.entry_id, None)
    if account and account.unsub:
        account.unsub()
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
