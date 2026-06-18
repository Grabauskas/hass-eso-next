"""Pure (Home Assistant-free) helpers that turn ESO datasets into the rows
written as long-term statistics.

Keeping this logic out of ``__init__.py`` makes it unit-testable without a
running Home Assistant instance. The critical invariant lives here: dataset
timestamps are *true UTC epochs* (produced by ``ESOClient.parse_dataset``),
so they line up with the recorder's hourly statistic keys, and ``local_datetime``
converts them back to Europe/Vilnius wall-clock for display.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Vilnius")


def local_datetime(ts: float) -> datetime:
    """Convert a true UTC epoch into an aware Europe/Vilnius datetime."""
    return datetime.fromtimestamp(ts, tz=LOCAL_TZ)


def build_energy_rows(generation_data: dict, previous_sum: float) -> list[dict]:
    """Build cumulative energy rows from ``{utc_epoch: kwh}``.

    Returns a list of ``{"start", "state", "sum"}`` dicts; the caller wraps
    them in ``StatisticData``.
    """
    rows: list[dict] = []
    running = previous_sum
    for ts, kwh in generation_data.items():
        running += kwh
        rows.append({"start": local_datetime(ts), "state": kwh, "sum": running})
    return rows


def build_cost_rows(cons_dataset: dict, prices: dict, previous_sum: float) -> list[dict]:
    """Build cumulative cost rows from consumption and a price-by-epoch map.

    ``prices`` is keyed by the same true UTC epochs as ``cons_dataset`` (both
    derive from the recorder/ESO hourly boundary), so the lookup hits. An hour
    with no matching price contributes 0 for that hour only.
    """
    rows: list[dict] = []
    running = previous_sum
    for ts, cons_kwh in cons_dataset.items():
        cost = round(cons_kwh * prices.get(ts, 0), 5)
        running += cost
        rows.append({"start": local_datetime(ts), "state": cost, "sum": running})
    return rows
