# custom_components/eso/account.py
"""Per-account ESO runtime: login, fetch, schedule, notify, statistics writes.

HA-dependent; excluded from unit tests/coverage. Both the YAML path and the UI
config-entry path build an EsoAccount and call the same methods.
"""
import asyncio
import logging
from datetime import datetime, timedelta

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
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CONSUMED,
    CONF_COST,
    CONF_ID,
    CONF_NAME,
    CONF_PRICE_CURRENCY,
    CONF_PRICE_ENTITY,
    CONF_RETURNED,
    DOMAIN,
    ENERGY_TYPE_MAP,
)
from .statistics_builder import build_cost_rows, build_energy_rows, local_datetime

_LOGGER = logging.getLogger(__name__)
RETRY_DELAY_SECONDS = 3 * 3600  # 3-hour pause between retries
NOTIFY_ID = "eso_tfa"


class EsoAccount:
    def __init__(self, hass, client, code_provider, objects, notify_after_failures, entry=None):
        self.hass = hass
        self.client = client
        self.code_provider = code_provider
        self.objects = objects
        self.notify_after_failures = notify_after_failures
        self.entry = entry
        self.failures = 0
        self.unsub = None  # scheduler cancel handle (config-entry accounts)

    def notify(self, message: str, title: str) -> None:
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=NOTIFY_ID
        )

    async def async_fetch_objects(self, now: datetime) -> None:
        any_failed = False
        for obj in self.objects:
            try:
                _LOGGER.info(f"Fetching ESO dataset [{obj[CONF_NAME]}]")
                await self.hass.async_add_executor_job(
                    self.client.fetch_dataset, obj[CONF_ID], now
                )
                dataset = self.client.get_dataset(obj[CONF_ID])
                await async_insert_statistics(self.hass, obj, dataset)
                if CONF_PRICE_ENTITY in obj and obj[CONF_PRICE_ENTITY]:
                    await async_insert_cost_statistics(self.hass, obj, dataset)
                _LOGGER.info(f"Import completed for {obj[CONF_NAME]}")
            except Exception as e:
                _LOGGER.error(f"Failed to import object {obj[CONF_NAME]}: {e}")
                any_failed = True
                continue
        if any_failed:
            raise RuntimeError("One or more ESO objects failed to import")

    async def handle_failure(self, retry: bool) -> None:
        self.failures += 1
        if self.failures == self.notify_after_failures:
            self.notify(
                "ESO automatic login failed repeatedly. Complete it manually: call "
                "eso.start_login, then eso.submit_tfa_code with the emailed code.",
                "ESO login needs attention",
            )
        if not retry:
            _LOGGER.warning("ESO import failed, will retry later")
            self.hass.loop.call_later(
                RETRY_DELAY_SECONDS,
                lambda: asyncio.create_task(
                    self.async_login_and_fetch(datetime.now(), retry=True)
                ),
            )
        else:
            _LOGGER.error("ESO import failed again, postponing to next day")

    async def async_login_and_fetch(self, now: datetime, retry: bool = False) -> None:
        if self.hass.is_stopping:
            _LOGGER.debug("HA is stopping, skipping ESO import")
            return
        if self.code_provider is None:
            if self.entry is not None:
                # UI entry without IMAP: drive the native reauth flow so the
                # user can enter the freshly emailed code from the UI.
                _LOGGER.debug("No imap on config entry; starting reauth flow")
                self.entry.async_start_reauth(self.hass)
            else:
                # YAML manual mode: handled by start_login/submit_tfa_code services.
                _LOGGER.debug("Skipping auto import: no imap config (manual mode)")
            return
        try:
            _LOGGER.info("Logging in to ESO (auto)...")
            await self.hass.async_add_executor_job(self.client.login)
            await self.async_fetch_objects(now)
        except Exception as e:
            _LOGGER.error(f"ESO auto import error: {e}")
            await self.handle_failure(retry)
            return
        self.failures = 0


async def async_insert_statistics(hass: HomeAssistant, obj: dict, dataset: dict) -> None:
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


async def _async_get_statistics(
    hass: HomeAssistant, metadata: StatisticMetaData, generation_data: dict
) -> list[StatisticData]:
    if not generation_data:
        return []
    first_ts = next(iter(generation_data))
    previous_sum = await get_previous_sum(hass, metadata, local_datetime(first_ts))
    rows = build_energy_rows(generation_data, previous_sum)
    return [StatisticData(start=r["start"], state=r["state"], sum=r["sum"]) for r in rows]


async def get_previous_sum(
    hass: HomeAssistant, metadata: StatisticMetaData, date: datetime
) -> float:
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
        # than writing all-zero cost stats.
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
    _LOGGER.debug(
        f"Generated cost statistics for {DOMAIN}:energy_{CONF_COST}_{obj[CONF_ID]}: {cost_stats}"
    )
    async_add_external_statistics(hass, cost_metadata, cost_stats)


async def _async_generate_price_dict(
    hass: HomeAssistant, obj: dict, time_from: datetime, time_to: datetime
) -> dict:
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, time_from, time_to,
        {obj[CONF_PRICE_ENTITY]}, "hour", None, {"state"},
    )
    price_stats = stats.get(obj[CONF_PRICE_ENTITY])
    if price_stats is None:
        _LOGGER.warning(
            "No price statistics for %s between %s and %s",
            obj[CONF_PRICE_ENTITY], time_from.isoformat(), time_to.isoformat(),
        )
        return {}
    _LOGGER.debug(
        "Retrieving price statistics for %s between %s and %s: %s",
        obj[CONF_PRICE_ENTITY], time_from, time_to, price_stats,
    )
    prices = {}
    for rec in price_stats:
        prices[rec["start"]] = rec["state"]
    return prices
