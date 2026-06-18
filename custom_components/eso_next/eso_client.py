import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

from .form_parser import FormParser

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
    """Raised when an email TFA code is required but cannot be supplied automatically."""


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
        if self.code_provider is None:
            raise TfaCodeNeeded("ESO requires an email code; configure imap or use the eso_next.start_login service")
        code = self.code_provider.wait_for_code(self._pending["requested_at"])
        self._submit_tfa(code)

    def start_login(self) -> bool:
        """Do the credential POST only. Returns True if a TFA code is now required."""
        self.dataset = {}
        return self._start_credentials()

    def submit_code(self, code: str) -> None:
        if not self._pending:
            raise TfaCodeNeeded("No pending ESO login; call start_login first")
        if datetime.now(timezone.utc) - self._pending["requested_at"] > TFA_CODE_TTL:
            self._pending = None
            raise TfaCodeNeeded("ESO code window expired; start the login again")
        self._submit_tfa(code)

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

    def fetch(self, obj: str, date: datetime) -> dict:
        if not self.cookies:
            _LOGGER.error("Cookies are empty. Check your credentials.")
            return {}
        if self.form_parser.get("form_id") != CONSUMPTION_FORM_ID:
            _LOGGER.error("Form ID not found. Check your credentials OR login to ESO and confirm contact information.")
            return {}
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
            return {}

    def fetch_dataset(self, obj: str, date: datetime) -> dict | None:
        if obj in self.dataset:
            return self.dataset[obj]
        self.dataset[obj] = {}
        data = self.fetch(obj, date)
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
                consumption_type = dataset["key"]
                if consumption_type not in self.dataset[obj]:
                    self.dataset[obj][consumption_type] = {}
                self.dataset[obj][consumption_type] = self.parse_dataset(dataset)
        return self.dataset[obj]

    def get_dataset(self, obj: str) -> dict | None:
        if obj not in self.dataset:
            return None
        return self.dataset[obj]

    @staticmethod
    def parse_dataset(dataset: dict) -> dict:
        result = {}
        for record in dataset["record"]:
            try:
                dt = datetime.strptime(record["date"], "%Y%m%d%H%M")
                ts = dt.timestamp()
                val = abs(float(record["value"])) if record["value"] is not None else 0.0
                result[ts] = val
            except Exception as e:
                _LOGGER.error(f"Failed to parse dataset record {record}: {e}")
        return result
