from datetime import datetime, timezone


def test_extract_code_simple(eso_module):
    extract_code = eso_module("imap_client").extract_code
    assert extract_code("Jūsų kodas:\n\n372449 \n\nKodas galioja 15 min.") == "372449"


def test_extract_code_none(eso_module):
    extract_code = eso_module("imap_client").extract_code
    assert extract_code("no digits here") is None
    assert extract_code(None) is None


def test_extract_code_from_real_email(eso_module, fixtures_path):
    import email
    extract_code = eso_module("imap_client").extract_code
    raw = (fixtures_path / "tfa_email.eml").read_bytes()
    msg = email.message_from_bytes(raw)
    text = None
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            text = part.get_payload(decode=True).decode("utf-8")
            break
    assert extract_code(text) == "372449"


def test_pick_code_newest_fresh(eso_module):
    mod = eso_module("imap_client")
    since = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
    candidates = [
        mod.Candidate(date=datetime(2026, 6, 17, 8, 55, tzinfo=timezone.utc),
                      sender="savitarna@eso.lt", subject="x", body="old 111111"),
        mod.Candidate(date=datetime(2026, 6, 17, 9, 5, tzinfo=timezone.utc),
                      sender="savitarna@eso.lt", subject="x", body="new 372449"),
    ]
    assert mod.pick_code(candidates, since) == "372449"


def test_pick_code_ignores_stale(eso_module):
    mod = eso_module("imap_client")
    since = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
    candidates = [
        mod.Candidate(date=datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc),
                      sender="savitarna@eso.lt", subject="x", body="old 111111"),
    ]
    assert mod.pick_code(candidates, since) is None


def test_build_search_criteria_quotes_multiword_subject(eso_module):
    mod = eso_module("imap_client")
    crit = mod.build_search_criteria(
        "savitarna@eso.lt", "ESO - Prisijungimo patvirtinimas", "17-Jun-2026"
    )
    # Subject contains spaces -> must be a single quoted IMAP string, otherwise
    # the server returns "BAD Could not parse command".
    assert crit == [
        "FROM", '"savitarna@eso.lt"',
        "SUBJECT", '"ESO - Prisijungimo patvirtinimas"',
        "SINCE", "17-Jun-2026",
    ]


def test_build_search_criteria_escapes_quotes(eso_module):
    mod = eso_module("imap_client")
    crit = mod.build_search_criteria('a"b@x.lt', 'sub "ject"', "01-Jan-2026")
    assert crit[1] == '"a\\"b@x.lt"'
    assert crit[3] == '"sub \\"ject\\""'


def test_imap_provider_init_stores_fields(eso_module):
    mod = eso_module("imap_client")
    p = mod.ImapCodeProvider("host", 993, "user", "pw", folder="F", sender="s@x", subject="subj")
    assert (p.host, p.port, p.username, p.password, p.folder, p.sender, p.subject) == (
        "host", 993, "user", "pw", "F", "s@x", "subj"
    )


def test_to_candidate_parses_real_eml(eso_module, fixtures_path):
    mod = eso_module("imap_client")
    raw = (fixtures_path / "tfa_email.eml").read_bytes()
    cand = mod.ImapCodeProvider._to_candidate(raw)
    assert cand.date.tzinfo is not None  # date is made tz-aware
    assert mod.extract_code(cand.body) == "372449"


class _FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL driven by canned fetch data."""

    def __init__(self, raw=None, search_ids=b"1"):
        self._raw = raw
        self._search_ids = search_ids

    def login(self, username, password):
        return ("OK", [b""])

    def select(self, folder):
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        return ("OK", [self._search_ids])

    def fetch(self, num, spec):
        return ("OK", [(b"1 (RFC822 {123}", self._raw)])

    def logout(self):
        return ("BYE", [b""])


def test_wait_for_code_returns_code_via_fake_imap(eso_module, fixtures_path, monkeypatch):
    from datetime import datetime, timezone

    mod = eso_module("imap_client")
    raw = (fixtures_path / "tfa_email.eml").read_bytes()
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: _FakeIMAP(raw=raw))

    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    # `since` older than the email date so pick_code accepts the message as fresh.
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert provider.wait_for_code(since, timeout=5, poll_interval=1) == "372449"


def test_check_connection_ok_with_fake_imap(eso_module, monkeypatch):
    mod = eso_module("imap_client")
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: _FakeIMAP())
    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    # A reachable server with accepted credentials returns without raising.
    assert provider.check_connection() is None


def test_check_connection_unreachable_raises_connect_error(eso_module, monkeypatch):
    import pytest

    mod = eso_module("imap_client")

    def _boom(host, port):
        raise OSError(101, "Network unreachable")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _boom)
    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    with pytest.raises(mod.ImapConnectError):
        provider.check_connection()


def test_check_connection_bad_login_raises_auth_error(eso_module, monkeypatch):
    import pytest

    mod = eso_module("imap_client")

    class _AuthFailIMAP(_FakeIMAP):
        def login(self, username, password):
            raise mod.imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: _AuthFailIMAP())
    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    with pytest.raises(mod.ImapAuthError):
        provider.check_connection()


def test_wait_for_code_retries_connect_error_until_deadline(eso_module, monkeypatch):
    """A network blip mid-wait must not abort the (unattended) login: connect
    errors are retried until the deadline, then surface as TfaTimeout rather than
    failing the whole login on the first hiccup."""
    import pytest

    mod = eso_module("imap_client")

    def _boom(host, port):
        raise OSError(101, "Network unreachable")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _boom)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(mod.TfaTimeout):
        provider.wait_for_code(since, timeout=0, poll_interval=0)


def test_wait_for_code_times_out_when_no_message(eso_module, monkeypatch):
    from datetime import datetime, timezone

    import pytest

    mod = eso_module("imap_client")
    # search returns no ids -> _poll_once yields None every time.
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", lambda host, port: _FakeIMAP(search_ids=b""))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    provider = mod.ImapCodeProvider("h", 993, "u", "pw")
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(mod.TfaTimeout):
        provider.wait_for_code(since, timeout=0, poll_interval=0)
