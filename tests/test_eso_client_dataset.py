from datetime import datetime
from zoneinfo import ZoneInfo

VILNIUS = ZoneInfo("Europe/Vilnius")


def _ts(stamp: str) -> float:
    # ESO reports wall-clock times in Europe/Vilnius; parse_dataset must turn
    # them into true UTC epochs (host-timezone independent) so they line up
    # with the recorder's hourly statistic keys.
    return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=VILNIUS).timestamp()


def test_parse_dataset_basic_and_abs_and_null(eso_module):
    ESOClient = eso_module("eso_client").ESOClient
    dataset = {
        "record": [
            {"date": "202606170800", "value": "1.5"},
            {"date": "202606170900", "value": "-2.0"},
            {"date": "202606171000", "value": None},
        ]
    }
    result = ESOClient.parse_dataset(dataset)
    assert result[_ts("202606170800")] == 1.5
    assert result[_ts("202606170900")] == 2.0  # abs() applied
    assert result[_ts("202606171000")] == 0.0  # None -> 0.0


def test_parse_dataset_skips_malformed_date(eso_module):
    ESOClient = eso_module("eso_client").ESOClient
    result = ESOClient.parse_dataset({"record": [{"date": "garbage", "value": "1.0"}]})
    assert result == {}


def test_fetch_dataset_extracts_records_and_updates_build_id(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    ajax = [
        {"command": "update_build_id", "new": "form-NEW"},
        {
            "command": "settings",
            "settings": {
                "eso_consumption_history_form": {
                    "graphics_data": {
                        "datasets": [
                            {"key": "P+", "record": [{"date": "202606170800", "value": "1.5"}]}
                        ]
                    }
                }
            },
        },
    ]
    client.fetch = lambda obj, date: ajax  # stub the HTTP layer
    result = client.fetch_dataset("123", datetime(2026, 6, 17))
    assert result["P+"][_ts("202606170800")] == 1.5
    assert client.form_parser.get("form_build_id") == "form-NEW"


def test_fetch_dataset_cached(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    client.dataset["123"] = {"P+": {1.0: 9.9}}
    # Already cached -> fetch() must not be called.
    client.fetch = lambda obj, date: (_ for _ in ()).throw(AssertionError("fetch called"))
    assert client.fetch_dataset("123", datetime(2026, 6, 17)) == {"P+": {1.0: 9.9}}


def test_fetch_no_cookies_returns_empty(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    client.cookies = None
    assert client.fetch("123", datetime(2026, 6, 17)) == {}


def test_fetch_wrong_form_returns_empty(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    client.cookies = {"x": "y"}
    # default form_parser has no form_id -> not the consumption form
    assert client.fetch("123", datetime(2026, 6, 17)) == {}


def test_get_dataset_missing_returns_none(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    assert client.get_dataset("nope") is None


class _FetchResponse:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text  # fetch() logs response.text at debug level

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FetchSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def post(self, url, data=None, headers=None, cookies=None, allow_redirects=True):
        self.calls.append({"url": url, "data": data})
        if self._exc is not None:
            raise self._exc
        return self._response


def _consumption_client(mod, session):
    client = mod.ESOClient("u", "p", session=session)
    client.cookies = {"SSESS": "abc"}
    client.form_parser.set("form_id", "eso_consumption_history_form")
    client.form_parser.set("form_build_id", "fb")
    client.form_parser.set("form_token", "tok")
    return client


def test_fetch_happy_path_returns_json(eso_module):
    mod = eso_module("eso_client")
    payload = [{"command": "settings", "settings": {}}]
    session = _FetchSession(response=_FetchResponse(payload))
    client = _consumption_client(mod, session)
    result = client.fetch("123", datetime(2026, 6, 17))
    assert result == payload
    assert session.calls[0]["data"]["objects[]"] == "123"


def test_fetch_request_exception_returns_empty(eso_module):
    import requests

    mod = eso_module("eso_client")
    session = _FetchSession(exc=requests.exceptions.RequestException("boom"))
    client = _consumption_client(mod, session)
    assert client.fetch("123", datetime(2026, 6, 17)) == {}


def test_get_dataset_present_returns_data(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    client.dataset["123"] = {"P+": {1.0: 5.0}}
    assert client.get_dataset("123") == {"P+": {1.0: 5.0}}


def test_fetch_dataset_ignores_non_settings_and_empty(eso_module):
    mod = eso_module("eso_client")
    client = mod.ESOClient("u", "p")
    client.fetch = lambda obj, date: [
        {"command": "insert", "data": "x"},                                  # non-settings
        {"command": "settings", "settings": {}},                             # key absent
        {"command": "settings", "settings": {"eso_consumption_history_form": None}},  # falsy
    ]
    assert client.fetch_dataset("zzz", datetime(2026, 6, 17)) == {}
