import asyncio
import logging
from datetime import datetime, timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import CONF_ID, CONF_NAME, CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .eso_client import ESOClient, TfaCodeNeeded
from .imap_client import DEFAULT_SENDER, DEFAULT_SUBJECT, ImapCodeProvider
from .statistics_builder import build_cost_rows, build_energy_rows, local_datetime

_LOGGER = logging.getLogger(__name__)
DOMAIN = "eso_next"
CONF_OBJECTS = "objects"
CONF_CONSUMED = "consumed"
CONF_RETURNED = "returned"
CONF_COST = "cost"
CONF_PRICE_ENTITY = "price_entity"
CONF_PRICE_CURRENCY = "price_currency"
CONF_IMAP = "imap"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_FOLDER = "folder"
CONF_SENDER = "sender"
CONF_SUBJECT = "subject"
CONF_NOTIFY_AFTER_FAILURES = "notify_after_failures"
POWER_CONSUMED = "P+"
POWER_RETURNED = "P-"
ENERGY_TYPE_MAP = {
    CONF_CONSUMED: POWER_CONSUMED,
    CONF_RETURNED: POWER_RETURNED
}
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

RETRY_DELAY_SECONDS = 3 * 3600  # 3 valandų pauzė tarp retry

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if DOMAIN not in config:
        return True
    hass.data.setdefault(DOMAIN, config[DOMAIN])
    conf = config[DOMAIN]
    code_provider = None
    if CONF_IMAP in conf:
        imap_conf = conf[CONF_IMAP]
        code_provider = ImapCodeProvider(
            host=imap_conf[CONF_HOST],
            port=imap_conf[CONF_PORT],
            username=imap_conf[CONF_USERNAME],
            password=imap_conf[CONF_PASSWORD],
            folder=imap_conf[CONF_FOLDER],
            sender=imap_conf[CONF_SENDER],
            subject=imap_conf[CONF_SUBJECT],
        )
    client = ESOClient(
        username=conf[CONF_USERNAME],
        password=conf[CONF_PASSWORD],
        code_provider=code_provider,
    )

    state = {"failures": 0}
    notify_after = conf[CONF_NOTIFY_AFTER_FAILURES]
    NOTIFY_ID = "eso_next_tfa"

    async def async_fetch_objects(now: datetime) -> None:
        any_failed = False
        for obj in conf[CONF_OBJECTS]:
            try:
                _LOGGER.info(f"Fetching ESO dataset [{obj[CONF_NAME]}]")
                await hass.async_add_executor_job(client.fetch_dataset, obj[CONF_ID], now)
                dataset = client.get_dataset(obj[CONF_ID])
                await async_insert_statistics(hass, obj, dataset)
                if CONF_PRICE_ENTITY in obj and obj[CONF_PRICE_ENTITY]:
                    await async_insert_cost_statistics(hass, obj, dataset)
                _LOGGER.info(f"Import completed for {obj[CONF_NAME]}")
            except Exception as e:
                _LOGGER.error(f"Failed to import object {obj[CONF_NAME]}: {e}")
                any_failed = True
                continue
        if any_failed:
            raise RuntimeError("One or more ESO objects failed to import")

    def _notify(message: str, title: str) -> None:
        persistent_notification.async_create(hass, message, title=title, notification_id=NOTIFY_ID)

    async def _handle_failure(retry: bool) -> None:
        state["failures"] += 1
        if state["failures"] == notify_after:
            _notify(
                "ESO automatic login failed repeatedly. Complete it manually: call "
                "eso_next.start_login, then eso_next.submit_tfa_code with the emailed code.",
                "ESO login needs attention",
            )
        if not retry:
            _LOGGER.warning("ESO import failed, will retry later")
            hass.loop.call_later(
                RETRY_DELAY_SECONDS,
                lambda: asyncio.create_task(async_auto_import(datetime.now(), retry=True)),
            )
        else:
            _LOGGER.error("ESO import failed again, postponing to next day")

    async def async_auto_import(now: datetime, retry: bool = False) -> None:
        if hass.is_stopping:
            _LOGGER.debug("HA is stopping, skipping ESO import")
            return
        try:
            _LOGGER.info("Logging in to ESO (auto)...")
            await hass.async_add_executor_job(client.login)
            await async_fetch_objects(now)
        except Exception as e:
            _LOGGER.error(f"ESO auto import error: {e}")
            await _handle_failure(retry)
            return
        state["failures"] = 0

    async def async_manual_reminder(now: datetime) -> None:
        if hass.is_stopping:
            return
        _notify(
            "Time to refresh ESO data. Call eso_next.start_login, then eso_next.submit_tfa_code "
            "with the code emailed to you.",
            "ESO data refresh due",
        )

    async def handle_start_login(call) -> None:
        try:
            needed = await hass.async_add_executor_job(client.start_login)
        except Exception as e:
            _LOGGER.error(f"ESO start_login error: {e}")
            _notify(f"ESO login failed to start: {e}", "ESO login error")
            return
        if needed:
            hass.bus.async_fire("eso_next_tfa_required", {})
            _notify(
                "ESO emailed you a login code. Submit it: call eso_next.submit_tfa_code "
                "with data code: '<the 6-digit code>'.",
                "ESO code required",
            )
        else:
            await async_fetch_objects(dt_util.now())
            persistent_notification.async_dismiss(hass, NOTIFY_ID)

    async def handle_submit_tfa_code(call) -> None:
        code = call.data["code"]
        try:
            await hass.async_add_executor_job(client.submit_code, code)
        except TfaCodeNeeded as e:
            _LOGGER.error(f"ESO submit_tfa_code rejected: {e}")
            _notify(f"ESO code rejected: {e}", "ESO code error")
            return
        except Exception as e:
            _LOGGER.error(f"ESO submit_tfa_code error: {e}")
            _notify(f"ESO login failed: {e}", "ESO login error")
            return
        await async_fetch_objects(dt_util.now())
        state["failures"] = 0
        persistent_notification.async_dismiss(hass, NOTIFY_ID)

    async def handle_fetch_now(call) -> None:
        if code_provider is None:
            _notify(
                "eso_next.fetch_now needs an imap: config block (auto mode). Without it, "
                "use eso_next.start_login then eso_next.submit_tfa_code.",
                "ESO fetch_now unavailable",
            )
            return
        await async_auto_import(dt_util.now())

    hass.services.async_register(DOMAIN, "fetch_now", handle_fetch_now)
    hass.services.async_register(DOMAIN, "start_login", handle_start_login)
    hass.services.async_register(
        DOMAIN,
        "submit_tfa_code",
        handle_submit_tfa_code,
        schema=vol.Schema({vol.Required("code"): cv.string}),
    )

    if code_provider is not None:
        async_track_time_change(hass, async_auto_import, hour=5, minute=11, second=0)
    else:
        async_track_time_change(hass, async_manual_reminder, hour=5, minute=11, second=0)
    return True

async def async_insert_statistics(
    hass: HomeAssistant, obj: dict, dataset: dict
) -> None:
    for data_type in [CONF_CONSUMED, CONF_RETURNED]:
        if obj[data_type] is False:
            continue
        statistic_id = f"{DOMAIN}:energy_{data_type}_{obj[CONF_ID]}"
        _LOGGER.debug(f"Statistic ID for {obj[CONF_NAME]} is {statistic_id}")
        mapped_consumption_type = ENERGY_TYPE_MAP[data_type]
        if not dataset or mapped_consumption_type not in dataset:
            _LOGGER.error(f"Received empty generation data for {statistic_id}")
            continue
        generation_data = dataset[mapped_consumption_type]
        _LOGGER.debug(f"Received ESO data for {statistic_id}: {generation_data}")
        metadata = StatisticMetaData(
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name=f"{obj[CONF_NAME]} ({data_type})",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class="energy",
        )
        _LOGGER.debug(f"Preparing long-term statistics for {statistic_id}")
        statistics = await _async_get_statistics(hass, metadata, generation_data)
        _LOGGER.debug(f"Generated statistics for {statistic_id}: {statistics}")
        async_add_external_statistics(hass, metadata, statistics)

async def _async_get_statistics(hass: HomeAssistant, metadata: StatisticMetaData, generation_data: dict) -> list[StatisticData]:
    if not generation_data:
        return []
    first_ts = next(iter(generation_data))
    previous_sum = await get_previous_sum(hass, metadata, local_datetime(first_ts))
    rows = build_energy_rows(generation_data, previous_sum)
    return [StatisticData(start=r["start"], state=r["state"], sum=r["sum"]) for r in rows]

async def get_previous_sum(hass: HomeAssistant, metadata: StatisticMetaData, date: datetime) -> float:
    statistic_id = metadata["statistic_id"]
    start = date - timedelta(hours=1)
    end = date
    _LOGGER.debug(f"Looking history sum for {statistic_id} for {date} between {start} and {end}")
    stat = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, end, {statistic_id}, "hour", None, {"sum"}
    )
    if statistic_id not in stat:
        _LOGGER.debug("No history sum found")
        return 0.0
    sum_ = stat[statistic_id][0]["sum"]
    _LOGGER.debug(f"History sum for {statistic_id} = {sum_}")
    return sum_

async def async_insert_cost_statistics(
    hass: HomeAssistant, obj: dict, consumption_dataset: dict
) -> None:
    if obj[CONF_CONSUMED] is False:
        return
    cons_dataset = consumption_dataset.get(ENERGY_TYPE_MAP[CONF_CONSUMED])
    if not cons_dataset:
        return
    start_time = local_datetime(min(cons_dataset.keys()))
    end_time = local_datetime(max(cons_dataset.keys()))
    prices = await _async_generate_price_dict(hass, obj, start_time, end_time)
    if not prices:
        # No price statistics available — skip cost insertion entirely rather
        # than writing all-zero cost stats (_async_generate_price_dict returns
        # an empty dict, never None, on the no-data path).
        return
    cost_metadata = StatisticMetaData(
        has_sum=True,
        mean_type=StatisticMeanType.NONE,
        name=f"{obj[CONF_NAME]} ({CONF_COST})",
        source=DOMAIN,
        statistic_id=f"{DOMAIN}:energy_{CONF_COST}_{obj[CONF_ID]}",
        unit_of_measurement=obj[CONF_PRICE_CURRENCY],
        unit_class=None,
    )
    previous_sum = await get_previous_sum(hass, cost_metadata, start_time)
    rows = build_cost_rows(cons_dataset, prices, previous_sum)
    cost_stats = [StatisticData(start=r["start"], state=r["state"], sum=r["sum"]) for r in rows]
    _LOGGER.debug(f"Generated cost statistics for {DOMAIN}:energy_{CONF_COST}_{obj[CONF_ID]}: {cost_stats}")
    async_add_external_statistics(hass, cost_metadata, cost_stats)

async def _async_generate_price_dict(
    hass: HomeAssistant, obj: dict, time_from: datetime, time_to: datetime
) -> dict:
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, time_from, time_to, {obj[CONF_PRICE_ENTITY]}, "hour", None, {"state"}
    )
    price_stats = stats.get(obj[CONF_PRICE_ENTITY])
    if price_stats is None:
        _LOGGER.warning(
            "No price statistics for %s between %s and %s", obj[CONF_PRICE_ENTITY], time_from.isoformat(), time_to.isoformat()
        )
        return {}
    _LOGGER.debug(
        "Retrieving price statistics for %s between %s and %s: %s", obj[CONF_PRICE_ENTITY], time_from, time_to, price_stats
    )
    prices = {}
    for rec in price_stats:
        prices[rec["start"]] = rec["state"]
    return prices
