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
