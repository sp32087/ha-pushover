"""The Pushover Advanced integration.

Provides full access to the Pushover Messages API (priorities, sounds,
URLs, HTML/monospace formatting, TTL, tags, attachments, emergency-priority
retry/expire and callback, receipt lookups, cancel-by-receipt and
cancel-by-tag) plus optional per-device end-to-end AES encryption, none of
which are exposed by Home Assistant's built-in Pushover integration.
"""
from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PushoverClient, PushoverMessage
from .const import (
    ALLOWED_ATTACHMENT_TYPES,
    ATTR_ATTACHMENT,
    ATTR_ATTACHMENT_BASE64,
    ATTR_ATTACHMENT_TYPE,
    ATTR_CALLBACK,
    ATTR_DEVICE,
    ATTR_ENCRYPT,
    ATTR_EXPIRE,
    ATTR_HTML,
    ATTR_MESSAGE,
    ATTR_MONOSPACE,
    ATTR_PRIORITY,
    ATTR_RECEIPT,
    ATTR_RETRY,
    ATTR_SOUND,
    ATTR_TAG,
    ATTR_TAGS,
    ATTR_TIMESTAMP,
    ATTR_TITLE,
    ATTR_TTL,
    ATTR_URL,
    ATTR_URL_TITLE,
    CONF_API_TOKEN,
    CONF_DEFAULT_EXPIRE,
    CONF_DEFAULT_RETRY,
    CONF_DEVICES,
    CONF_ENCRYPTION_KEY,
    CONF_USER_KEY,
    DATA_CLIENTS,
    DEFAULT_ENCRYPTED_TITLE,
    DOMAIN,
    MAX_ATTACHMENT_BYTES,
    MAX_EXPIRE_SECONDS,
    MAX_MESSAGE_LENGTH,
    MAX_RETRY_SECONDS,
    MAX_TAGS_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_URL_LENGTH,
    MAX_URL_TITLE_LENGTH,
    MIN_RETRY_SECONDS,
    MIN_TTL_SECONDS,
    PRIORITY_EMERGENCY,
    SERVICE_CANCEL_BY_TAG,
    SERVICE_CANCEL_RECEIPT,
    SERVICE_GET_RECEIPT,
    SERVICE_SEND_MESSAGE,
)
from .crypto import encrypt_field
from .exceptions import PushoverAuthError, PushoverEncryptionError, PushoverError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY]

CONF_ENTRY = "config_entry_id"


def _validate_tags(tags: list[str]) -> list[str]:
    """Enforce Pushover's combined tags length limit."""
    if len(",".join(tags)) > MAX_TAGS_LENGTH:
        raise vol.Invalid(f"tags must total {MAX_TAGS_LENGTH} characters or fewer once joined")
    return tags


SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY): cv.string,
        vol.Required(ATTR_MESSAGE): vol.All(cv.string, vol.Length(min=1, max=MAX_MESSAGE_LENGTH)),
        vol.Optional(ATTR_TITLE): vol.All(cv.string, vol.Length(min=1, max=MAX_TITLE_LENGTH)),
        vol.Optional(ATTR_PRIORITY): vol.All(vol.Coerce(int), vol.In([-2, -1, 0, 1, 2])),
        vol.Optional(ATTR_SOUND): cv.string,
        vol.Optional(ATTR_URL): vol.All(cv.url, vol.Length(max=MAX_URL_LENGTH)),
        vol.Optional(ATTR_URL_TITLE): vol.All(
            cv.string, vol.Length(min=1, max=MAX_URL_TITLE_LENGTH)
        ),
        vol.Optional(ATTR_DEVICE): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_TIMESTAMP): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_HTML): cv.boolean,
        vol.Optional(ATTR_MONOSPACE): cv.boolean,
        vol.Optional(ATTR_TTL): vol.All(vol.Coerce(int), vol.Range(min=MIN_TTL_SECONDS)),
        vol.Optional(ATTR_TAGS): vol.All(cv.ensure_list, [cv.string], _validate_tags),
        vol.Optional(ATTR_CALLBACK): cv.url,
        vol.Optional(ATTR_RETRY): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_RETRY_SECONDS, max=MAX_RETRY_SECONDS)
        ),
        vol.Optional(ATTR_EXPIRE): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_EXPIRE_SECONDS)
        ),
        vol.Optional(ATTR_ATTACHMENT): cv.isfile,
        vol.Optional(ATTR_ATTACHMENT_BASE64): cv.string,
        vol.Optional(ATTR_ATTACHMENT_TYPE): vol.In(ALLOWED_ATTACHMENT_TYPES),
        vol.Optional(ATTR_ENCRYPT, default=False): cv.boolean,
    }
)

CANCEL_RECEIPT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY): cv.string,
        vol.Required(ATTR_RECEIPT): cv.string,
    }
)

CANCEL_BY_TAG_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY): cv.string,
        vol.Required(ATTR_TAG): cv.string,
    }
)

GET_RECEIPT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY): cv.string,
        vol.Required(ATTR_RECEIPT): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pushover Advanced from a config entry."""
    session = async_get_clientsession(hass)
    client = PushoverClient(session, entry.data[CONF_API_TOKEN], entry.data[CONF_USER_KEY])

    try:
        await client.validate_user()
    except PushoverAuthError as err:
        raise ConfigEntryNotReady(f"Pushover credentials rejected: {err}") from err
    except PushoverError as err:
        raise ConfigEntryNotReady(f"Unable to reach Pushover: {err}") from err

    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_CLIENTS, {})[entry.entry_id] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        clients = hass.data.get(DOMAIN, {}).get(DATA_CLIENTS, {})
        clients.pop(entry.entry_id, None)
        if not clients:
            hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
            hass.services.async_remove(DOMAIN, SERVICE_CANCEL_RECEIPT)
            hass.services.async_remove(DOMAIN, SERVICE_CANCEL_BY_TAG)
            hass.services.async_remove(DOMAIN, SERVICE_GET_RECEIPT)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options (devices/defaults) change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    """Pick which configured Pushover account/app a service call applies to."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("No Pushover Advanced accounts are configured.")

    entry_id = call.data.get(CONF_ENTRY)
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise HomeAssistantError(f"Unknown config_entry_id: {entry_id}")
        return entry

    if len(entries) > 1:
        raise HomeAssistantError(
            "Multiple Pushover Advanced accounts are configured; "
            "specify config_entry_id to choose one."
        )
    return entries[0]


def _client_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> PushoverClient:
    return hass.data[DOMAIN][DATA_CLIENTS][entry.entry_id]


def _maybe_encrypt(entry: ConfigEntry, message: PushoverMessage) -> None:
    """Encrypt message/title in place if encryption was requested for this call."""
    devices = message.device or []
    if len(devices) != 1:
        raise HomeAssistantError(
            "Encryption requires targeting exactly one device (the device that "
            "holds the matching secret); got: "
            f"{devices or 'no device specified'}."
        )

    device_options = entry.options.get(CONF_DEVICES, {}).get(devices[0])
    if not device_options or CONF_ENCRYPTION_KEY not in device_options:
        raise HomeAssistantError(
            f"No encryption secret configured for device '{devices[0]}'. "
            "Add one from the integration's options before using encrypt: true."
        )

    key_hex = device_options[CONF_ENCRYPTION_KEY]
    # If no title is given, Pushover fills one in itself (the application's
    # name) in plaintext - but with encrypted=1 set, the receiving device
    # tries to decrypt every text field it's handed, title included, and
    # fails on that plaintext default. Always encrypt an explicit title so
    # there's nothing left in plaintext for it to choke on.
    title = message.title if message.title is not None else DEFAULT_ENCRYPTED_TITLE
    try:
        message.message = encrypt_field(message.message, key_hex)
        message.title = encrypt_field(title, key_hex)
    except PushoverEncryptionError as err:
        raise HomeAssistantError(f"Encryption failed: {err}") from err
    message.encrypted = True


async def _async_handle_send_message(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _resolve_entry(hass, call)
    client = _client_for_entry(hass, entry)
    data = call.data

    if data.get(ATTR_HTML) and data.get(ATTR_MONOSPACE):
        raise HomeAssistantError("html and monospace cannot both be enabled.")

    priority = data.get(ATTR_PRIORITY)
    retry = data.get(ATTR_RETRY)
    expire = data.get(ATTR_EXPIRE)
    if priority == PRIORITY_EMERGENCY:
        retry = retry or entry.options.get(CONF_DEFAULT_RETRY)
        expire = expire or entry.options.get(CONF_DEFAULT_EXPIRE)
        if retry is None or expire is None:
            raise HomeAssistantError(
                "priority: 2 (emergency) requires retry and expire, either in the "
                "service call or as integration defaults."
            )
        if retry >= expire:
            raise HomeAssistantError(
                f"retry ({retry}s) must be less than expire ({expire}s), "
                "otherwise the message would never actually be retried."
            )

    if ATTR_ATTACHMENT in data and ATTR_ATTACHMENT_BASE64 in data:
        raise HomeAssistantError("Specify either attachment or attachment_base64, not both.")

    attachment_bytes: bytes | None = None
    if ATTR_ATTACHMENT in data:
        path = data[ATTR_ATTACHMENT]
        if not hass.config.is_allowed_path(path):
            raise HomeAssistantError(f"'{path}' is not an allowed path for attachments.")
        attachment_bytes = await hass.async_add_executor_job(Path(path).read_bytes)
        if len(attachment_bytes) > MAX_ATTACHMENT_BYTES:
            raise HomeAssistantError(
                f"Attachment exceeds Pushover's {MAX_ATTACHMENT_BYTES} byte "
                f"({MAX_ATTACHMENT_BYTES / 1_048_576:.1f} MB) limit."
            )

    if ATTR_ATTACHMENT_BASE64 in data:
        try:
            decoded_size = len(base64.b64decode(data[ATTR_ATTACHMENT_BASE64], validate=True))
        except (binascii.Error, ValueError) as err:
            raise HomeAssistantError(f"attachment_base64 is not valid base64: {err}") from err
        if decoded_size > MAX_ATTACHMENT_BYTES:
            raise HomeAssistantError(
                f"attachment_base64 decodes to {decoded_size} bytes, which exceeds "
                f"Pushover's {MAX_ATTACHMENT_BYTES} byte ({MAX_ATTACHMENT_BYTES / 1_048_576:.1f} MB) limit."
            )

    message = PushoverMessage(
        message=data[ATTR_MESSAGE],
        title=data.get(ATTR_TITLE),
        priority=priority,
        sound=data.get(ATTR_SOUND),
        url=data.get(ATTR_URL),
        url_title=data.get(ATTR_URL_TITLE),
        device=data.get(ATTR_DEVICE),
        timestamp=data.get(ATTR_TIMESTAMP),
        html=data.get(ATTR_HTML),
        monospace=data.get(ATTR_MONOSPACE),
        ttl=data.get(ATTR_TTL),
        tags=data.get(ATTR_TAGS),
        callback=data.get(ATTR_CALLBACK),
        retry=retry,
        expire=expire,
        attachment=attachment_bytes,
        attachment_base64=data.get(ATTR_ATTACHMENT_BASE64),
        attachment_type=data.get(ATTR_ATTACHMENT_TYPE),
    )

    if data.get(ATTR_ENCRYPT):
        _maybe_encrypt(entry, message)

    try:
        response = await client.send_message(message)
    except PushoverError as err:
        raise HomeAssistantError(str(err)) from err

    return {
        "status": response.status,
        "request": response.request_id,
        "receipt": response.receipt,
    }


async def _async_handle_cancel_receipt(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _resolve_entry(hass, call)
    client = _client_for_entry(hass, entry)
    try:
        result = await client.cancel_receipt(call.data[ATTR_RECEIPT])
    except PushoverError as err:
        raise HomeAssistantError(str(err)) from err
    return {"status": result.get("status")}


async def _async_handle_cancel_by_tag(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _resolve_entry(hass, call)
    client = _client_for_entry(hass, entry)
    try:
        result = await client.cancel_by_tag(call.data[ATTR_TAG])
    except PushoverError as err:
        raise HomeAssistantError(str(err)) from err
    return {"status": result.get("status")}


async def _async_handle_get_receipt(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _resolve_entry(hass, call)
    client = _client_for_entry(hass, entry)
    try:
        result = await client.get_receipt(call.data[ATTR_RECEIPT])
    except PushoverError as err:
        raise HomeAssistantError(str(err)) from err
    return result


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain services (idempotent across multiple config entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    async def _send_message(call: ServiceCall) -> ServiceResponse:
        return await _async_handle_send_message(hass, call)

    async def _cancel_receipt(call: ServiceCall) -> ServiceResponse:
        return await _async_handle_cancel_receipt(hass, call)

    async def _cancel_by_tag(call: ServiceCall) -> ServiceResponse:
        return await _async_handle_cancel_by_tag(hass, call)

    async def _get_receipt(call: ServiceCall) -> ServiceResponse:
        return await _async_handle_get_receipt(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        _send_message,
        schema=SEND_MESSAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_RECEIPT,
        _cancel_receipt,
        schema=CANCEL_RECEIPT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_BY_TAG,
        _cancel_by_tag,
        schema=CANCEL_BY_TAG_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RECEIPT,
        _get_receipt,
        schema=GET_RECEIPT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
