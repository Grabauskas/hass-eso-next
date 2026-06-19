def test_build_object_applies_defaults(eso_module):
    cm = eso_module("config_model")
    obj = cm.build_object({"name": "Home", "id": "12345"})
    assert obj == {
        "name": "Home", "id": "12345",
        "consumed": True, "returned": False, "price_currency": "EUR",
    }
    assert "price_entity" not in obj  # omitted when not provided


def test_build_object_keeps_price_entity_when_set(eso_module):
    cm = eso_module("config_model")
    obj = cm.build_object({
        "name": "Home", "id": "1", "consumed": False, "returned": True,
        "price_entity": "sensor.price", "price_currency": "USD",
    })
    assert obj["consumed"] is False
    assert obj["returned"] is True
    assert obj["price_entity"] == "sensor.price"
    assert obj["price_currency"] == "USD"


def test_build_object_drops_empty_price_entity(eso_module):
    cm = eso_module("config_model")
    obj = cm.build_object({"name": "H", "id": "1", "price_entity": ""})
    assert "price_entity" not in obj


def test_imap_provider_kwargs_defaults(eso_module):
    cm = eso_module("config_model")
    kw = cm.imap_provider_kwargs({"host": "imap.x", "username": "u", "password": "p"})
    assert kw == {
        "host": "imap.x", "port": 993, "username": "u", "password": "p",
        "folder": "INBOX", "sender": "savitarna@eso.lt",
        "subject": "ESO - Prisijungimo patvirtinimas",
    }


def test_imap_provider_kwargs_overrides(eso_module):
    cm = eso_module("config_model")
    kw = cm.imap_provider_kwargs({
        "host": "imap.x", "port": 143, "username": "u", "password": "p",
        "folder": "Mail", "sender": "a@b.c", "subject": "Subj",
    })
    assert kw["port"] == 143
    assert kw["folder"] == "Mail"
    assert kw["sender"] == "a@b.c"
    assert kw["subject"] == "Subj"


def test_imap_block_none_without_host(eso_module):
    cm = eso_module("config_model")
    assert cm.imap_block({"username": "esouser", "password": "esopass"}) is None
    assert cm.imap_block({"username": "esouser", "password": "esopass", "host": ""}) is None


def test_imap_block_defaults_imap_creds_to_eso_creds(eso_module):
    cm = eso_module("config_model")
    block = cm.imap_block({
        "username": "esouser", "password": "esopass", "host": "imap.x",
    })
    assert block == {
        "host": "imap.x", "port": 993,
        "username": "esouser", "password": "esopass",
        "folder": "INBOX", "sender": "savitarna@eso.lt",
        "subject": "ESO - Prisijungimo patvirtinimas",
    }


def test_imap_block_uses_explicit_imap_creds(eso_module):
    cm = eso_module("config_model")
    block = cm.imap_block({
        "username": "esouser", "password": "esopass", "host": "imap.x",
        "imap_username": "mailuser", "imap_password": "mailpass", "port": 143,
    })
    assert block["username"] == "mailuser"
    assert block["password"] == "mailpass"
    assert block["port"] == 143


def test_object_id_in_use_detects_duplicate(eso_module):
    cm = eso_module("config_model")
    assert cm.object_id_in_use(["111", "222"], "222") is True


def test_object_id_in_use_ignores_surrounding_whitespace(eso_module):
    cm = eso_module("config_model")
    assert cm.object_id_in_use(["111"], "  111 ") is True


def test_object_id_in_use_false_for_new_id(eso_module):
    cm = eso_module("config_model")
    assert cm.object_id_in_use(["111", "222"], "333") is False


def test_duplicate_object_ids_returns_overlap(eso_module):
    cm = eso_module("config_model")
    assert cm.duplicate_object_ids(["111", "222"], ["222", "333"]) == ["222"]


def test_duplicate_object_ids_trims_and_dedups(eso_module):
    cm = eso_module("config_model")
    # Whitespace-insensitive match, and each clashing id reported once.
    assert cm.duplicate_object_ids(["111"], [" 111 ", "111", "  "]) == ["111"]


def test_duplicate_object_ids_empty_when_disjoint(eso_module):
    cm = eso_module("config_model")
    assert cm.duplicate_object_ids(["111", "222"], ["333"]) == []
