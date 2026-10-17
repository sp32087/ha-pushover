"""Tests for the encryption glue in __init__.py (_maybe_encrypt).

Home Assistant's ConfigEntry is stubbed to a plain namespace here since
_maybe_encrypt only ever reads entry.options - see tests/conftest.py for
why the package has to be importable without a real homeassistant install.
"""
from __future__ import annotations

import base64
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
from custom_components.pushover_advanced.crypto import decrypt_bytes, decrypt_field

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


def test_url_and_url_title_are_encrypted_when_present() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(
        message="hello",
        device=["phone"],
        url="https://example.com/dashboard",
        url_title="Open dashboard",
    )

    _maybe_encrypt(entry, message)

    assert decrypt_field(message.url, DEVICE_KEY) == "https://example.com/dashboard"
    assert decrypt_field(message.url_title, DEVICE_KEY) == "Open dashboard"


def test_url_stays_absent_when_not_given() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone"])

    _maybe_encrypt(entry, message)

    assert message.url is None
    assert message.url_title is None


def test_attachment_is_left_unencrypted_but_warns(caplog: pytest.LogCaptureFixture) -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone"], attachment=b"raw-image-bytes")

    _maybe_encrypt(entry, message)

    assert message.attachment == b"raw-image-bytes"
    assert any("does not cover attachments" in record.message for record in caplog.records)


def test_attachment_base64_also_warns(caplog: pytest.LogCaptureFixture) -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(
        message="hello", device=["phone"], attachment_base64="ZGF0YQ=="
    )

    _maybe_encrypt(entry, message)

    assert message.attachment_base64 == "ZGF0YQ=="
    assert any("does not cover attachments" in record.message for record in caplog.records)


def test_no_attachment_means_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone"])

    _maybe_encrypt(entry, message)

    assert not any("does not cover attachments" in record.message for record in caplog.records)


def test_encrypt_attachment_encrypts_raw_bytes_and_switches_to_base64(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(
        message="hello", device=["phone"], attachment=b"raw-image-bytes"
    )

    _maybe_encrypt(entry, message, encrypt_attachment=True)

    assert message.attachment is None
    assert decrypt_bytes(message.attachment_base64, DEVICE_KEY) == b"raw-image-bytes"
    assert any(
        "encrypt_attachment: true" in record.message for record in caplog.records
    )


def test_encrypt_attachment_encrypts_existing_base64() -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    plaintext_b64 = base64.b64encode(b"a real jpeg, honest").decode("ascii")
    message = PushoverMessage(
        message="hello", device=["phone"], attachment_base64=plaintext_b64
    )

    _maybe_encrypt(entry, message, encrypt_attachment=True)

    assert message.attachment_base64 != plaintext_b64
    assert decrypt_bytes(message.attachment_base64, DEVICE_KEY) == b"a real jpeg, honest"


def test_encrypt_attachment_false_leaves_default_warning_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _entry({"phone": {CONF_ENCRYPTION_KEY: DEVICE_KEY}})
    message = PushoverMessage(message="hello", device=["phone"], attachment=b"raw")

    _maybe_encrypt(entry, message, encrypt_attachment=False)

    assert message.attachment == b"raw"
    assert any("does not cover attachments" in record.message for record in caplog.records)


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
