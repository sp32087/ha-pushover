"""Tests for the AES-256-CBC + HMAC-SHA256 per-device encryption scheme."""
from __future__ import annotations

import base64

import pytest

from custom_components.pushover_advanced.crypto import (
    decrypt_field,
    encrypt_field,
    self_test,
    validate_key_hex,
)
from custom_components.pushover_advanced.exceptions import PushoverEncryptionError

VALID_KEY = "00" * 32  # 64 hex chars = 32 bytes


def test_validate_key_hex_accepts_valid_key() -> None:
    assert validate_key_hex(VALID_KEY) == VALID_KEY


def test_validate_key_hex_normalizes_case() -> None:
    assert validate_key_hex("AB" * 32) == ("ab" * 32)


@pytest.mark.parametrize(
    "bad_key",
    [
        "too-short",
        "zz" * 32,  # not hex
        "0" * 63,  # odd length / too short
        "0" * 65,  # too long
        "",
    ],
)
def test_validate_key_hex_rejects_invalid(bad_key: str) -> None:
    with pytest.raises(PushoverEncryptionError):
        validate_key_hex(bad_key)


def test_round_trip() -> None:
    plaintext = "The garage door has been open for 10 minutes."
    ciphertext = encrypt_field(plaintext, VALID_KEY)
    assert decrypt_field(ciphertext, VALID_KEY) == plaintext


def test_round_trip_unicode() -> None:
    plaintext = "Türen offen — 🚪 warnung"
    ciphertext = encrypt_field(plaintext, VALID_KEY)
    assert decrypt_field(ciphertext, VALID_KEY) == plaintext


def test_ciphertext_is_base64_and_not_plaintext() -> None:
    plaintext = "hello world"
    ciphertext = encrypt_field(plaintext, VALID_KEY)
    assert plaintext not in ciphertext
    # must be valid base64
    base64.b64decode(ciphertext)


def test_each_encryption_uses_a_fresh_iv() -> None:
    plaintext = "same message"
    first = encrypt_field(plaintext, VALID_KEY)
    second = encrypt_field(plaintext, VALID_KEY)
    assert first != second


def test_wrong_key_fails_hmac_check() -> None:
    ciphertext = encrypt_field("secret", VALID_KEY)
    other_key = "11" * 32
    with pytest.raises(PushoverEncryptionError):
        decrypt_field(ciphertext, other_key)


def test_tampered_ciphertext_fails_hmac_check() -> None:
    ciphertext = encrypt_field("secret", VALID_KEY)
    raw = bytearray(base64.b64decode(ciphertext))
    raw[-1] ^= 0xFF
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(PushoverEncryptionError):
        decrypt_field(tampered, VALID_KEY)


def test_self_test_passes_for_valid_key() -> None:
    assert self_test(VALID_KEY) is True
