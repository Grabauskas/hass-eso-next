from datetime import datetime, timedelta, timezone


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
