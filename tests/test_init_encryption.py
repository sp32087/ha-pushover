"""Tests for the encryption glue in __init__.py (_maybe_encrypt).

Home Assistant's ConfigEntry is stubbed to a plain namespace here since
_maybe_encrypt only ever reads entry.options - see tests/conftest.py for
why the package has to be importable without a real homeassistant install.
"""
from __future__ import annotations

import types

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.pushover_advanced import _maybe_encrypt
from custom_components.pushover_advanced.api import PushoverMessage
from custom_components.pushover_advanced.const import (
    CONF_DEVICES,
    CONF_ENCRYPTION_KEY,
    DEFAULT_ENCRYPTED_TITLE,
)
from custom_components.pushover_advanced.crypto import decrypt_field

DEVICE_KEY = "ab" * 32


def _entry(devices: dict | None = None) -> types.SimpleNamespace:
    return types.SimpleNamespace(options={CONF_DEVICES: devices or {}})


def test_missing_title_defaults_before_encrypting() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone"])

    _maybe_encrypt(entry, message)

    assert message.encrypted is True
    assert decrypt_field(message.title, DEVICE_KEY) == DEFAULT_ENCRYPTED_TITLE
    assert decrypt_field(message.message, DEVICE_KEY) == "hello"


def test_explicit_title_is_still_encrypted_as_given() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", title="Garage door", device=["phone"])

    _maybe_encrypt(entry, message)

    assert decrypt_field(message.title, DEVICE_KEY) == "Garage door"


def test_requires_exactly_one_device() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone", "tablet"])

    with pytest.raises(HomeAssistantError):
        _maybe_encrypt(entry, message)


def test_requires_a_configured_key_for_the_device() -> None:
    entry = _entry({})
    message = PushoverMessage(message="hello", device=["phone"])

    with pytest.raises(HomeAssistantError):
        _maybe_encrypt(entry, message)
