"""End-to-end encryption helper for Pushover's per-device AES secrets.

Pushover's iOS/Android/desktop apps support an optional end-to-end
encryption mode: each device that opts in generates a random 256-bit
secret (shown in the app as a 64-character hex string) which is entered
into the sending client. The sending client then encrypts the ``message``
and (optionally) ``title`` fields itself before they ever leave the local
network, sets ``encrypted=1`` on the API request, and Pushover's servers
and the Apple/Google push transport only ever see ciphertext.

The scheme, as documented by Pushover ("Implement End-to-End Encryption"),
is a standard encrypt-then-MAC construction:

    key   = the 32-byte secret (64 hex chars, as shown in the app)
    iv    = 16 random bytes, generated fresh for every field encrypted
    ct    = AES-256-CBC(key, iv, PKCS7(utf-8 plaintext))
    tag   = HMAC-SHA256(key, iv || ct)
    value = base64(iv || ct || tag)

The resulting base64 string is sent in place of the plaintext value of the
field it replaces (e.g. the ``message`` parameter itself becomes the
ciphertext, rather than being sent under a separate parameter name).

Because Pushover does not publish a machine-readable spec for this
feature, this module has been implemented directly from their support
documentation and has not been validated against a live encrypted device
registration. Verify round-trip decryption with your own device before
relying on this for anything security-critical.
"""
from __future__ import annotations

import base64
import hmac
import os
import re
from hashlib import sha256

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .exceptions import PushoverEncryptionError

KEY_LENGTH_BYTES = 32
IV_LENGTH_BYTES = 16
HMAC_LENGTH_BYTES = 32

_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_key_hex(key_hex: str) -> str:
    """Validate (and normalize) a 64-character hex AES secret.

    Raises PushoverEncryptionError if the value isn't a well-formed
    32-byte hex-encoded key.
    """
    key_hex = key_hex.strip()
    if not _HEX_KEY_RE.match(key_hex):
        raise PushoverEncryptionError(
            "Encryption secrets must be exactly 64 hex characters "
            "(the 256-bit secret shown in the Pushover app for the device)."
        )
    return key_hex.lower()


def _key_bytes(key_hex: str) -> bytes:
    return bytes.fromhex(validate_key_hex(key_hex))


def encrypt_field(plaintext: str, key_hex: str) -> str:
    """Encrypt a single field value for a device's AES secret.

    Returns the base64-encoded ``iv || ciphertext || hmac`` blob that
    should be sent in place of the plaintext value.
    """
    key = _key_bytes(key_hex)
    iv = os.urandom(IV_LENGTH_BYTES)

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    tag = hmac.new(key, iv + ciphertext, sha256).digest()

    return base64.b64encode(iv + ciphertext + tag).decode("ascii")


def decrypt_field(value_b64: str, key_hex: str) -> str:
    """Decrypt a field previously produced by encrypt_field.

    Provided mainly so device secrets can be self-tested (encrypt then
    decrypt) from the config/options flow before being saved.
    """
    key = _key_bytes(key_hex)
    raw = base64.b64decode(value_b64)

    if len(raw) < IV_LENGTH_BYTES + HMAC_LENGTH_BYTES:
        raise PushoverEncryptionError("Encrypted payload is too short to be valid.")

    iv = raw[:IV_LENGTH_BYTES]
    tag = raw[-HMAC_LENGTH_BYTES:]
    ciphertext = raw[IV_LENGTH_BYTES:-HMAC_LENGTH_BYTES]

    expected_tag = hmac.new(key, iv + ciphertext, sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise PushoverEncryptionError("HMAC verification failed; wrong key or corrupted payload.")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    return plaintext.decode("utf-8")


def self_test(key_hex: str) -> bool:
    """Round-trip a canary string through encrypt/decrypt to sanity-check a key."""
    canary = "pushover-advanced-self-test"
    return decrypt_field(encrypt_field(canary, key_hex), key_hex) == canary
