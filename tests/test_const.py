def test_const_exports(eso_module):
    const = eso_module("const")
    assert const.DOMAIN == "eso"
    assert const.ENERGY_TYPE_MAP == {const.CONF_CONSUMED: "P+", const.CONF_RETURNED: "P-"}
    assert const.DEFAULT_PORT == 993
    assert const.DEFAULT_FOLDER == "INBOX"
    assert const.DEFAULT_PRICE_CURRENCY == "EUR"
    assert const.DEFAULT_NOTIFY_AFTER_FAILURES == 2
    # DEFAULT_SENDER/SUBJECT re-exported from imap_client (single source of truth)
    assert const.DEFAULT_SENDER == eso_module("imap_client").DEFAULT_SENDER
