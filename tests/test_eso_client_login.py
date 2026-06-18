from datetime import datetime, timedelta, timezone

import pytest
import requests

CONSUMPTION_HTML = """
<form id="eso-form" action="/consumption" method="post">
  <input name="form_id" value="eso_consumption_history_form" />
  <input name="form_build_id" value="form-CONS" />
  <input name="form_token" value="tok-CONS" />
</form>
"""

# What ESO re-renders when credentials are wrong: the login form, no TFA.
LOGIN_PAGE_HTML = """
<form id="user-login-form" action="/" method="post">
  <input name="form_id" value="user_login_form" />
  <input name="form_build_id" value="form-LOGIN" />
</form>
"""


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.cookies.set("SSESS", "abc", domain="mano.eso.lt")

    def post(self, url, data=None, headers=None, cookies=None, allow_redirects=True):
        self.calls.append({"url": url, "data": data})
        return self._responses.pop(0)


def _tfa_html(fixtures_path):
    return (fixtures_path / "tfa_page.html").read_text(encoding="utf-8")


class FakeProvider:
    def __init__(self, code):
        self.code = code
        self.since = None

    def wait_for_code(self, since, **kwargs):
        self.since = since
        return self.code


def test_login_auto_submits_code(eso_module, fixtures_path):
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern22djUGPyjorvNonwdGNVbdNRhaUI37LUXjlgsI?destination=/consumption"
    session = FakeSession([
        FakeResponse(_tfa_html(fixtures_path), tfa_url),
        FakeResponse(CONSUMPTION_HTML, "https://mano.eso.lt/consumption"),
    ])
    provider = FakeProvider("372449")
    client = mod.ESOClient("user", "pass", code_provider=provider, session=session)

    client.login()

    # Second POST went to the absolute TFA action URL with the code + fields.
    second = session.calls[1]
    assert second["url"] == "https://mano.eso.lt/user/login/tfa/1286168/-Gern22djUGPyjorvNonwdGNVbdNRhaUI37LUXjlgsI"
    assert second["data"]["code"] == "372449"
    assert second["data"]["form_id"] == "gpc_tfa_login_auth_form"
    assert second["data"]["form_build_id"] == "form-D9AvTpq4nDOrqtATuSxtgQzylt68ZkUCl8LbusBgApE"
    assert second["data"]["submit_code"] == "Submit code"
    # Landed on the consumption form so fetch() will work.
    assert client.form_parser.get("form_id") == "eso_consumption_history_form"


def test_login_without_provider_raises_and_stores_pending(eso_module, fixtures_path):
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern?destination=/consumption"
    session = FakeSession([FakeResponse(_tfa_html(fixtures_path), tfa_url)])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)

    try:
        client.login()
        assert False, "expected TfaCodeNeeded"
    except mod.TfaCodeNeeded:
        pass

    assert client._pending is not None
    assert client._pending["form_build_id"] == "form-D9AvTpq4nDOrqtATuSxtgQzylt68ZkUCl8LbusBgApE"


def test_submit_code_completes_pending(eso_module, fixtures_path):
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern?destination=/consumption"
    session = FakeSession([
        FakeResponse(_tfa_html(fixtures_path), tfa_url),
        FakeResponse(CONSUMPTION_HTML, "https://mano.eso.lt/consumption"),
    ])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)

    assert client.start_login() is True
    client.submit_code("654321")

    assert session.calls[1]["data"]["code"] == "654321"
    assert client._pending is None


def test_start_login_no_tfa_returns_false(eso_module):
    mod = eso_module("eso_client")
    session = FakeSession([
        FakeResponse(CONSUMPTION_HTML, "https://mano.eso.lt/consumption"),
    ])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)

    assert client.start_login() is False
    assert client._pending is None
    assert client.form_parser.get("form_id") == "eso_consumption_history_form"


def test_submit_code_window_expired(eso_module, fixtures_path):
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern?destination=/consumption"
    session = FakeSession([FakeResponse(_tfa_html(fixtures_path), tfa_url)])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)
    client.start_login()
    client._pending["requested_at"] = datetime.now(timezone.utc) - timedelta(minutes=20)

    try:
        client.submit_code("654321")
        assert False, "expected TfaCodeNeeded"
    except mod.TfaCodeNeeded:
        pass


def test_is_authenticated_true_on_consumption_page(eso_module):
    mod = eso_module("eso_client")
    session = FakeSession([FakeResponse(CONSUMPTION_HTML, "https://mano.eso.lt/consumption")])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)
    client.start_login()
    assert client.is_authenticated() is True


def test_is_authenticated_false_on_login_page(eso_module):
    mod = eso_module("eso_client")
    session = FakeSession([FakeResponse(LOGIN_PAGE_HTML, "https://mano.eso.lt/")])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)
    client.start_login()
    assert client.is_authenticated() is False


def test_start_login_bad_credentials_returns_false_and_not_authenticated(eso_module):
    """Bad creds: ESO re-renders the login page, so no TFA and not authenticated.

    Without this distinction the config flow would create a broken entry.
    """
    mod = eso_module("eso_client")
    session = FakeSession([FakeResponse(LOGIN_PAGE_HTML, "https://mano.eso.lt/")])
    client = mod.ESOClient("user", "wrong", code_provider=None, session=session)

    assert client.start_login() is False
    assert client.is_authenticated() is False


def test_submit_code_no_pending_raises_session_expired(eso_module):
    mod = eso_module("eso_client")
    session = FakeSession([])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)

    with pytest.raises(mod.TfaSessionExpired):
        client.submit_code("123456")


def test_submit_code_expiry_raises_session_expired(eso_module, fixtures_path):
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern?destination=/consumption"
    session = FakeSession([FakeResponse(_tfa_html(fixtures_path), tfa_url)])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)
    client.start_login()
    client._pending["requested_at"] = datetime.now(timezone.utc) - timedelta(minutes=20)

    with pytest.raises(mod.TfaSessionExpired):
        client.submit_code("654321")


def test_submit_code_rejected_when_still_on_tfa_page(eso_module, fixtures_path):
    """A wrong code: ESO re-renders the TFA form. This must be reported as a
    rejected code (TfaCodeNeeded), NOT a silent success that creates the entry,
    and NOT a session-expiry."""
    mod = eso_module("eso_client")
    tfa_url = "https://mano.eso.lt/user/login/tfa/1286168/-Gern?destination=/consumption"
    session = FakeSession([
        FakeResponse(_tfa_html(fixtures_path), tfa_url),   # start_login -> TFA form
        FakeResponse(_tfa_html(fixtures_path), tfa_url),   # submit -> still TFA (rejected)
    ])
    client = mod.ESOClient("user", "pass", code_provider=None, session=session)
    client.start_login()

    with pytest.raises(mod.TfaCodeNeeded) as exc:
        client.submit_code("000000")
    assert not isinstance(exc.value, mod.TfaSessionExpired)
    assert client.is_authenticated() is False
    # The challenge is rebuilt so the user can retry within the TTL window.
    assert client._pending is not None
