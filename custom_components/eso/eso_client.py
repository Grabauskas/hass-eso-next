import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from .form_parser import FormParser

# ESO reports consumption timestamps as wall-clock time in Lithuania.
LOCAL_TZ = ZoneInfo("Europe/Vilnius")

LOGIN_URL = "https://mano.eso.lt/?destination=/consumption"
GENERATION_URL = "https://mano.eso.lt/consumption?ajax_form=1&_wrapper_format=drupal_ajax"
MONTHS = [
    "Sausio", "Vasario", "Kovo", "Balandžio", "Gegužės", "Birželio", "Liepos", "Rugpjūčio", "Rugsėjo", "Spalio", "Lapkričio", "Gruodžio"
]
_LOGGER = logging.getLogger(__name__)

TFA_FORM_ID = "gpc_tfa_login_auth_form"
CONSUMPTION_FORM_ID = "eso_consumption_history_form"
TFA_CODE_TTL = timedelta(minutes=15)


class TfaCodeNeeded(Exception):
    """Raised when an email TFA code is required but cannot be supplied automatically,
    or when a submitted code was rejected and a fresh code can still be entered."""


class TfaSessionExpired(TfaCodeNeeded):
    """Raised when there is no pending login or the code window has lapsed.

    Distinct from a merely-wrong code: the caller must mint a fresh challenge
    (re-POST credentials) before another code can be submitted. Subclasses
    TfaCodeNeeded so existing ``except TfaCodeNeeded`` handlers still catch it."""


class ESOFetchError(Exception):
    """Raised when a consumption fetch fails for a hard reason (not logged-in,
    wrong page, or a network error). Distinguishes a genuine failure from ESO
    simply having no data, so the caller's failure/notification logic engages
    instead of silently treating the failure as an empty result."""


class ESOClient:
    def __init__(self, username: str, password: str, code_provider=None, session: requests.Session | None = None):
        self.username: str = username
        self.password: str = password
        self.code_provider = code_provider
        self.session: requests.Session = session or requests.Session()
        self.cookies: dict | None = None
        self.form_parser: FormParser = FormParser()
        self.dataset: dict = {}
        self._pending: dict | None = None

    def login(self) -> None:
        self.dataset = {}
        if not self._start_credentials():
            return  # no TFA challenge; already at consumption page
        self.finish_login()

    def finish_login(self) -> None:
        """Complete an auto-mode login after start_login(): wait for the emailed
        code via the configured provider, then submit it. Split out from login()
        so the UI config flow can run this part as a background task (with a
        progress indicator) after the fast credential POST."""
        if self.code_provider is None:
            raise TfaCodeNeeded("ESO requires an email code; configure imap or use the eso.start_login service")
        if not self._pending:
            raise TfaSessionExpired("No pending ESO login; start the login again")
        code = self.code_provider.wait_for_code(self._pending["requested_at"])
        self._submit_tfa(code)

    def start_login(self) -> bool:
        """Do the credential POST only. Returns True if a TFA code is now required."""
        self.dataset = {}
        return self._start_credentials()

    def is_authenticated(self) -> bool:
        """True once the session has landed on the consumption page (login done)."""
        return self.form_parser.get("form_id") == CONSUMPTION_FORM_ID

    def submit_code(self, code: str) -> None:
        if not self._pending:
            raise TfaSessionExpired("No pending ESO login; start the login again")
        if datetime.now(timezone.utc) - self._pending["requested_at"] > TFA_CODE_TTL:
            self._pending = None
            raise TfaSessionExpired("ESO code window expired; start the login again")
        prev = self._pending
        self._submit_tfa(code)  # clears self._pending
        if self.is_authenticated():
            return
        if self.form_parser.get("form_id") == TFA_FORM_ID:
            # ESO re-rendered the TFA form: the code was wrong. Rebuild a pending
            # challenge from the re-rendered form (picking up any new build id)
            # while preserving the original requested_at, so the user can retry
            # within the same TTL window instead of being trapped.
            action = self.form_parser.get("action")
            self._pending = {
                "action_url": urljoin(prev["action_url"], action) if action else prev["action_url"],
                "form_build_id": self.form_parser.get("form_build_id") or prev["form_build_id"],
                "requested_at": prev["requested_at"],
            }
        raise TfaCodeNeeded("ESO rejected the code; check your email and try again")

    def _start_credentials(self) -> bool:
        """POST credentials. Returns True if a TFA challenge is present (pending stored)."""
        self._pending = None
        requested_at = datetime.now(timezone.utc)
        response = self.session.post(
            LOGIN_URL,
            data={
                "name": self.username,
                "pass": self.password,
                "login_type": 1,
                "form_id": "user_login_form",
            },
            allow_redirects=True,
        )
        response.raise_for_status()
        _LOGGER.debug("Got login response")
        self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
        self.form_parser = FormParser()
        self.form_parser.feed(response.text)
        if self.form_parser.get("form_id") != TFA_FORM_ID:
            return False
        action = self.form_parser.get("action") or ""
        self._pending = {
            "action_url": urljoin(response.url, action),
            "form_build_id": self.form_parser.get("form_build_id"),
            "requested_at": requested_at,
        }
        return True

    def _submit_tfa(self, code: str) -> None:
        if not self._pending:
            raise TfaCodeNeeded("No pending ESO login")
        data = {
            "code": code,
            "form_build_id": self._pending["form_build_id"],
            "form_id": TFA_FORM_ID,
            "submit_code": "Submit code",
        }
        response = self.session.post(self._pending["action_url"], data=data, allow_redirects=True)
        response.raise_for_status()
        _LOGGER.debug("Got TFA submit response")
        self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
        self.form_parser = FormParser()
        self.form_parser.feed(response.text)
        self._pending = None

    def fetch(self, obj: str, date: datetime) -> list:
        if not self.cookies:
            _LOGGER.error("Cookies are empty. Check your credentials.")
            raise ESOFetchError("Not logged in to ESO (no session cookies)")
        if self.form_parser.get("form_id") != CONSUMPTION_FORM_ID:
            _LOGGER.error("Form ID not found. Check your credentials OR login to ESO and confirm contact information.")
            raise ESOFetchError("Not on the ESO consumption page")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }
        data = {
            "objects[]": obj,
            "objects_mock": "",
            "display_type": "hourly",
            "period": "week",
            "energy_type": "general",
            "scales": "total",
            "active_date_value": date.strftime("%Y-%m-%d 00:00"),
            "made_energy_status": 1,
            "visible_scales_field": 0,
            "visible_last_year_comparison_field": 0,
            "form_build_id": self.form_parser.get("form_build_id"),
            "form_token": self.form_parser.get("form_token"),
            "form_id": self.form_parser.get("form_id"),
            "_drupal_ajax": "1",
            "_triggering_element_name": "display_type",
        }
        try:
            response = self.session.post(
                GENERATION_URL,
                data=data,
                headers=headers,
                cookies=self.cookies,
                allow_redirects=False
            )
            response.raise_for_status()
            _LOGGER.debug(f"Got fetch response: {response.text}")
            return response.json()
        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"ESO fetch error: {e}")
            raise ESOFetchError(str(e)) from e

    def fetch_dataset(self, obj: str, date: datetime) -> dict:
        if obj in self.dataset:
            return self.dataset[obj]
        # Build into a local dict and only cache on success, so a hard failure
        # (ESOFetchError) doesn't leave an empty cached entry that would mask
        # the data on a later retry.
        data = self.fetch(obj, date)
        result: dict = {}
        for d in data:
            if d.get("command") == "update_build_id":
                self.form_parser.set("form_build_id", d["new"])
                continue
            if d.get("command") != "settings":
                continue
            if "eso_consumption_history_form" not in d["settings"] or not d["settings"]["eso_consumption_history_form"]:
                continue
            datasets = d["settings"]["eso_consumption_history_form"]["graphics_data"]["datasets"]
            for dataset in datasets:
                result[dataset["key"]] = self.parse_dataset(dataset)
        self.dataset[obj] = result
        return result

    def get_dataset(self, obj: str) -> dict | None:
        if obj not in self.dataset:
            return None
        return self.dataset[obj]

    @staticmethod
    def parse_dataset(dataset: dict) -> dict:
        # ESO timestamps are wall-clock in Europe/Vilnius. Interpret them in
        # that zone (not the host's local zone) so the resulting UTC epochs are
        # host-timezone independent and match the recorder's hourly statistic
        # keys — required for the cost-price lookup to line up.
        #
        # Known limitation: on the autumn DST fall-back, 02:00–03:00 occurs
        # twice but the wall-clock string can't disambiguate the two instances
        # (fold defaults to 0), so one of that day's duplicated hours collides.
        result = {}
        for record in dataset["record"]:
            try:
                dt = datetime.strptime(record["date"], "%Y%m%d%H%M").replace(tzinfo=LOCAL_TZ)
                ts = dt.timestamp()
                val = abs(float(record["value"])) if record["value"] is not None else 0.0
                result[ts] = val
            except Exception as e:
                _LOGGER.error(f"Failed to parse dataset record {record}: {e}")
        return result
