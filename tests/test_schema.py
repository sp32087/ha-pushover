"""Tests that SEND_MESSAGE_SCHEMA actually enforces Pushover's documented limits."""
from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.pushover_advanced import SEND_MESSAGE_SCHEMA
from custom_components.pushover_advanced.const import (
    MAX_EXPIRE_SECONDS,
    MAX_MESSAGE_LENGTH,
    MAX_RETRY_SECONDS,
    MAX_TAGS_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_RETRY_SECONDS,
)


def test_accepts_a_minimal_valid_call() -> None:
    result = SEND_MESSAGE_SCHEMA({"message": "hello"})
    assert result["message"] == "hello"
    assert result["encrypt"] is False


def test_rejects_message_too_long() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "x" * (MAX_MESSAGE_LENGTH + 1)})


def test_rejects_empty_message() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": ""})


def test_rejects_title_too_long() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "title": "x" * (MAX_TITLE_LENGTH + 1)})


@pytest.mark.parametrize("priority", [-3, 3, 10])
def test_rejects_out_of_range_priority(priority: int) -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "priority": priority})


@pytest.mark.parametrize("priority", [-2, -1, 0, 1, 2])
def test_accepts_every_valid_priority(priority: int) -> None:
    result = SEND_MESSAGE_SCHEMA({"message": "hi", "priority": priority})
    assert result["priority"] == priority


def test_rejects_zero_ttl() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "ttl": 0})


def test_accepts_positive_ttl() -> None:
    result = SEND_MESSAGE_SCHEMA({"message": "hi", "ttl": 60})
    assert result["ttl"] == 60


def test_rejects_retry_below_minimum() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "retry": MIN_RETRY_SECONDS - 1})


def test_rejects_retry_above_maximum() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "retry": MAX_RETRY_SECONDS + 1})


def test_rejects_expire_above_maximum() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "expire": MAX_EXPIRE_SECONDS + 1})


def test_rejects_tags_over_combined_length() -> None:
    tags = ["a" * 50] * 5  # 250 chars once joined, over the 200 char limit
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "tags": tags})


def test_accepts_tags_within_combined_length() -> None:
    tags = ["a" * 50] * 3  # 150 chars once joined
    result = SEND_MESSAGE_SCHEMA({"message": "hi", "tags": tags})
    assert len(",".join(result["tags"])) <= MAX_TAGS_LENGTH


def test_rejects_invalid_url() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "url": "not a url"})


def test_accepts_valid_url() -> None:
    result = SEND_MESSAGE_SCHEMA({"message": "hi", "url": "https://example.com"})
    assert result["url"] == "https://example.com"


def test_rejects_invalid_callback_url() -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "callback": "not a url"})


@pytest.mark.parametrize("mime_type", ["image/jpeg", "image/png", "image/gif"])
def test_accepts_allowed_attachment_types(mime_type: str) -> None:
    result = SEND_MESSAGE_SCHEMA({"message": "hi", "attachment_type": mime_type})
    assert result["attachment_type"] == mime_type


@pytest.mark.parametrize("mime_type", ["image/webp", "application/pdf", "text/plain"])
def test_rejects_unsupported_attachment_types(mime_type: str) -> None:
    with pytest.raises(vol.Invalid):
        SEND_MESSAGE_SCHEMA({"message": "hi", "attachment_type": mime_type})
