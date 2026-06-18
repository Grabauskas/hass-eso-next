from datetime import datetime
from zoneinfo import ZoneInfo

VILNIUS = ZoneInfo("Europe/Vilnius")


def _vilnius_epoch(stamp: str) -> float:
    """True UTC epoch of a Vilnius wall-clock 'YYYYMMDDHHMM' string."""
    return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=VILNIUS).timestamp()


def test_local_datetime_round_trips_to_vilnius_wall_clock(eso_module):
    sb = eso_module("statistics_builder")
    # Summer (EEST, UTC+3) and winter (EET, UTC+2) must both land on the
    # original wall-clock hour, independent of the host system timezone.
    summer = sb.local_datetime(_vilnius_epoch("202606170800"))
    winter = sb.local_datetime(_vilnius_epoch("202601170800"))
    assert (summer.year, summer.month, summer.day, summer.hour) == (2026, 6, 17, 8)
    assert summer.utcoffset().total_seconds() == 3 * 3600
    assert (winter.year, winter.month, winter.day, winter.hour) == (2026, 1, 17, 8)
    assert winter.utcoffset().total_seconds() == 2 * 3600


def test_build_energy_rows_seeds_and_accumulates_sum(eso_module):
    sb = eso_module("statistics_builder")
    data = {
        _vilnius_epoch("202606170800"): 1.5,
        _vilnius_epoch("202606170900"): 2.0,
    }
    rows = sb.build_energy_rows(data, previous_sum=10.0)
    assert [r["state"] for r in rows] == [1.5, 2.0]
    assert [r["sum"] for r in rows] == [11.5, 13.5]
    assert rows[0]["start"].hour == 8 and rows[1]["start"].hour == 9


def test_build_cost_rows_matches_price_keyed_by_recorder_utc_epoch(eso_module):
    """Regression for the cost-key timezone bug: consumption keys produced by
    parse_dataset must line up with recorder price keys (true UTC epochs), so
    the price lookup hits rather than silently falling back to 0."""
    sb = eso_module("statistics_builder")
    ts = _vilnius_epoch("202606170800")
    cons = {ts: 4.0}
    prices = {ts: 0.25}  # recorder keys hourly stats by true UTC epoch
    rows = sb.build_cost_rows(cons, prices, previous_sum=0.0)
    assert rows[0]["state"] == 1.0  # 4.0 kWh * 0.25 — NOT 0
    assert rows[0]["sum"] == 1.0


def test_build_cost_rows_missing_price_is_zero_for_that_hour(eso_module):
    sb = eso_module("statistics_builder")
    ts = _vilnius_epoch("202606170800")
    rows = sb.build_cost_rows({ts: 4.0}, prices={}, previous_sum=0.0)
    assert rows[0]["state"] == 0.0
