"""Shared constants for the ESO integration (pure, HA-free, importable in tests)."""
from .imap_client import DEFAULT_SENDER as DEFAULT_SENDER  # noqa: F401
from .imap_client import DEFAULT_SUBJECT as DEFAULT_SUBJECT

# String values match homeassistant.const exactly.
CONF_ID = "id"
CONF_NAME = "name"
CONF_PASSWORD = "password"
CONF_USERNAME = "username"

DOMAIN = "eso"

CONF_OBJECTS = "objects"
CONF_CONSUMED = "consumed"
CONF_RETURNED = "returned"
CONF_COST = "cost"
CONF_PRICE_ENTITY = "price_entity"
CONF_PRICE_CURRENCY = "price_currency"
CONF_IMAP = "imap"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_FOLDER = "folder"
CONF_SENDER = "sender"
CONF_SUBJECT = "subject"
CONF_NOTIFY_AFTER_FAILURES = "notify_after_failures"
CONF_CODE = "code"

POWER_CONSUMED = "P+"
POWER_RETURNED = "P-"
ENERGY_TYPE_MAP = {
    CONF_CONSUMED: POWER_CONSUMED,
    CONF_RETURNED: POWER_RETURNED,
}

DEFAULT_PORT = 993
DEFAULT_FOLDER = "INBOX"
DEFAULT_PRICE_CURRENCY = "EUR"
DEFAULT_NOTIFY_AFTER_FAILURES = 2
