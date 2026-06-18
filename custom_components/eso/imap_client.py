import email
import imaplib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

_LOGGER = logging.getLogger(__name__)

CODE_RE = re.compile(r"\b(\d{6})\b")
DEFAULT_SENDER = "savitarna@eso.lt"
DEFAULT_SUBJECT = "ESO - Prisijungimo patvirtinimas"


class TfaTimeout(Exception):
    """Raised when no fresh TFA code arrives within the timeout."""


class ImapConnectError(Exception):
    """Raised when the IMAP server cannot be reached (DNS, network, TLS, socket).

    Lets callers show a clear 'could not reach your mail server' message instead
    of leaking a raw ``OSError`` as an opaque 'unknown' error."""


class ImapAuthError(Exception):
    """Raised when the IMAP server rejects the supplied username/password."""


@dataclass
class Candidate:
    date: datetime
    sender: str
    subject: str
    body: str


def extract_code(text: str | None) -> str | None:
    if not text:
        return None
    match = CODE_RE.search(text)
    return match.group(1) if match else None


def _quote(value: str) -> str:
    """Wrap a value as an IMAP quoted string, escaping backslashes and quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_search_criteria(sender: str, subject: str, since_day: str) -> list[str]:
    """Build IMAP SEARCH criteria. FROM/SUBJECT values are quoted so multi-word
    strings (e.g. the ESO subject) don't break command parsing."""
    return ["FROM", _quote(sender), "SUBJECT", _quote(subject), "SINCE", since_day]


def pick_code(
    candidates: list[Candidate],
    since: datetime,
    skew: timedelta = timedelta(seconds=30),
) -> str | None:
    threshold = since - skew
    fresh = [c for c in candidates if c.date >= threshold]
    if not fresh:
        return None
    newest = max(fresh, key=lambda c: c.date)
    return extract_code(newest.body)


class ImapCodeProvider:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        folder: str = "INBOX",
        sender: str = DEFAULT_SENDER,
        subject: str = DEFAULT_SUBJECT,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self.sender = sender
        self.subject = subject

    def wait_for_code(self, since: datetime, timeout: int = 120, poll_interval: int = 5) -> str:
        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)
        while True:
            code = self._poll_once(since)
            if code is not None:
                return code
            if datetime.now(timezone.utc) >= deadline:
                raise TfaTimeout(
                    f"No ESO TFA code from {self.sender} within {timeout}s"
                )
            time.sleep(poll_interval)

    def check_connection(self) -> None:
        """Fast reachability + credential check: connect, log in, log out — no
        polling. Raises ImapConnectError / ImapAuthError so the config flow can
        fail fast with a clear message instead of blocking on wait_for_code()."""
        imap = self._connect_and_login()
        try:
            imap.logout()
        except Exception:  # noqa: BLE001 - logout best-effort
            pass

    def _connect_and_login(self) -> imaplib.IMAP4_SSL:
        """Open the SSL connection and authenticate, mapping low-level failures
        to ImapConnectError (unreachable) / ImapAuthError (bad credentials)."""
        try:
            imap = imaplib.IMAP4_SSL(self.host, self.port)
        except (OSError, imaplib.IMAP4.error) as e:
            raise ImapConnectError(str(e)) from e
        try:
            imap.login(self.username, self.password)
        except imaplib.IMAP4.error as e:
            self._safe_logout(imap)
            raise ImapAuthError(str(e)) from e
        except OSError as e:
            self._safe_logout(imap)
            raise ImapConnectError(str(e)) from e
        return imap

    @staticmethod
    def _safe_logout(imap) -> None:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001 - logout best-effort
            pass

    def _poll_once(self, since: datetime) -> str | None:
        imap = self._connect_and_login()
        try:
            imap.select(self.folder)
            since_day = since.strftime("%d-%b-%Y")
            criteria = build_search_criteria(self.sender, self.subject, since_day)
            typ, data = imap.search(None, *criteria)
            if typ != "OK" or not data or not data[0]:
                return None
            candidates = []
            for num in data[0].split():
                typ, msg_data = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                candidates.append(self._to_candidate(msg_data[0][1]))
            return pick_code(candidates, since)
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001 - logout best-effort
                pass

    @staticmethod
    def _to_candidate(raw: bytes) -> Candidate:
        msg = email.message_from_bytes(raw)
        try:
            date = parsedate_to_datetime(msg.get("Date"))
        except (TypeError, ValueError):
            date = datetime.now(timezone.utc)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
        if not body:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")
        return Candidate(
            date=date,
            sender=msg.get("From", ""),
            subject=msg.get("Subject", ""),
            body=body,
        )
