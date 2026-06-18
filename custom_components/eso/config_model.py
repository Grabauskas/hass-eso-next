"""Pure helpers turning raw config/form dicts into runtime shapes."""
from .const import (
    CONF_CONSUMED,
    CONF_FOLDER,
    CONF_HOST,
    CONF_ID,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USERNAME,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_PRICE_CURRENCY,
    CONF_PRICE_ENTITY,
    CONF_RETURNED,
    CONF_SENDER,
    CONF_SUBJECT,
    CONF_USERNAME,
    DEFAULT_FOLDER,
    DEFAULT_PORT,
    DEFAULT_PRICE_CURRENCY,
    DEFAULT_SENDER,
    DEFAULT_SUBJECT,
)


def build_object(data: dict) -> dict:
    """Normalize a config/subentry dict into the canonical runtime object dict."""
    obj = {
        CONF_NAME: data[CONF_NAME],
        CONF_ID: data[CONF_ID],
        CONF_CONSUMED: data.get(CONF_CONSUMED, True),
        CONF_RETURNED: data.get(CONF_RETURNED, False),
        CONF_PRICE_CURRENCY: data.get(CONF_PRICE_CURRENCY) or DEFAULT_PRICE_CURRENCY,
    }
    price_entity = data.get(CONF_PRICE_ENTITY)
    if price_entity:
        obj[CONF_PRICE_ENTITY] = price_entity
    return obj


def imap_provider_kwargs(data: dict) -> dict:
    """Map an IMAP config dict to ImapCodeProvider kwargs, applying defaults."""
    return {
        "host": data[CONF_HOST],
        "port": data.get(CONF_PORT, DEFAULT_PORT),
        "username": data[CONF_USERNAME],
        "password": data[CONF_PASSWORD],
        "folder": data.get(CONF_FOLDER) or DEFAULT_FOLDER,
        "sender": data.get(CONF_SENDER) or DEFAULT_SENDER,
        "subject": data.get(CONF_SUBJECT) or DEFAULT_SUBJECT,
    }


def imap_block(user_input: dict) -> dict | None:
    """Build the stored IMAP block from the flat config-flow form.

    Returns None when no IMAP host is given (manual/reauth mode). IMAP
    credentials default to the ESO credentials when left blank.
    """
    if not user_input.get(CONF_HOST):
        return None
    return {
        CONF_HOST: user_input[CONF_HOST],
        CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: user_input.get(CONF_IMAP_USERNAME) or user_input[CONF_USERNAME],
        CONF_PASSWORD: user_input.get(CONF_IMAP_PASSWORD) or user_input[CONF_PASSWORD],
        CONF_FOLDER: user_input.get(CONF_FOLDER, DEFAULT_FOLDER),
        CONF_SENDER: user_input.get(CONF_SENDER, DEFAULT_SENDER),
        CONF_SUBJECT: user_input.get(CONF_SUBJECT, DEFAULT_SUBJECT),
    }


def object_id_in_use(existing_ids, new_id: str) -> bool:
    """True if new_id (whitespace-trimmed) collides with an existing object id.

    Duplicate object ids would produce colliding statistic ids and duplicate
    fetches, so the subentry flow rejects them.
    """
    target = (new_id or "").strip()
    return any(target == (existing or "").strip() for existing in existing_ids)
