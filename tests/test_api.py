"""Tests for the Pushover API client against mocked HTTP responses."""
from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.pushover_advanced.api import (
    PushoverClient,
    PushoverMessage,
    encode_attachment_base64,
)
from custom_components.pushover_advanced.const import (
    API_CANCEL_BY_TAG_URL,
    API_CANCEL_RECEIPT_URL,
    API_GROUP_URL,
    API_MESSAGES_URL,
    API_RECEIPT_URL,
    API_VALIDATE_URL,
)
from custom_components.pushover_advanced.exceptions import (
    PushoverApiError,
    PushoverAuthError,
    PushoverRateLimitError,
)

TOKEN = "atoken1234567890123456789012"
USER = "auser1234567890123456789012"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as sess:
        yield sess


@pytest.fixture
def client(session):
    return PushoverClient(session, TOKEN, USER)


def test_to_form_fields_minimal() -> None:
    msg = PushoverMessage(message="hello")
    assert msg.to_form_fields() == {"message": "hello"}


def test_to_form_fields_full() -> None:
    msg = PushoverMessage(
        message="hello",
        title="hi",
        priority=1,
        sound="siren",
        url="https://example.com",
        url_title="Example",
        device=["phone", "desktop"],
        timestamp=1700000000,
        html=True,
        monospace=False,
        ttl=60,
        tags=["a", "b"],
        callback="https://example.com/cb",
        retry=60,
        expire=3600,
        attachment_base64="ZGF0YQ==",
        attachment_type="image/jpeg",
        encrypted=True,
    )
    fields = msg.to_form_fields()
    assert fields["message"] == "hello"
    assert fields["title"] == "hi"
    assert fields["priority"] == "1"
    assert fields["sound"] == "siren"
    assert fields["device"] == "phone,desktop"
    assert fields["html"] == "1"
    assert "monospace" not in fields  # False -> omitted
    assert fields["tags"] == "a,b"
    assert fields["retry"] == "60"
    assert fields["expire"] == "3600"
    assert fields["attachment_base64"] == "ZGF0YQ=="
    assert fields["attachment_type"] == "image/jpeg"
    assert fields["encrypted"] == "1"


@pytest.mark.asyncio
async def test_validate_user_success(client) -> None:
    with aioresponses() as m:
        m.post(API_VALIDATE_URL, payload={"status": 1, "devices": ["phone"], "request": "r1"})
        result = await client.validate_user()
        assert result["status"] == 1
        assert result["devices"] == ["phone"]


@pytest.mark.asyncio
async def test_validate_user_bad_token_raises_auth_error(client) -> None:
    with aioresponses() as m:
        m.post(
            API_VALIDATE_URL,
            status=400,
            payload={"status": 0, "errors": ["application token is invalid"]},
        )
        with pytest.raises(PushoverAuthError):
            await client.validate_user()


@pytest.mark.asyncio
async def test_send_message_returns_receipt_for_emergency(client) -> None:
    with aioresponses() as m:
        m.post(
            API_MESSAGES_URL,
            payload={"status": 1, "request": "req-1", "receipt": "rcpt-1"},
        )
        response = await client.send_message(PushoverMessage(message="fire!", priority=2))
        assert response.ok
        assert response.request_id == "req-1"
        assert response.receipt == "rcpt-1"


@pytest.mark.asyncio
async def test_send_message_multipart_for_attachment(client) -> None:
    with aioresponses() as m:
        m.post(API_MESSAGES_URL, payload={"status": 1, "request": "req-1"})
        response = await client.send_message(
            PushoverMessage(message="see attached", attachment=b"fake-bytes")
        )
        assert response.ok
        request = m.requests[("POST", aiohttp.client.URL(API_MESSAGES_URL))][0]
        assert isinstance(request.kwargs["data"], aiohttp.FormData)


@pytest.mark.asyncio
async def test_send_message_error_response_raises_api_error(client) -> None:
    with aioresponses() as m:
        m.post(
            API_MESSAGES_URL,
            status=400,
            payload={"status": 0, "errors": ["message length too long"]},
        )
        with pytest.raises(PushoverApiError) as exc_info:
            await client.send_message(PushoverMessage(message="x" * 2000))
        assert "message length too long" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_message_rate_limit(client) -> None:
    with aioresponses() as m:
        m.post(API_MESSAGES_URL, status=429, payload={"status": 0, "errors": ["limit reached"]})
        with pytest.raises(PushoverRateLimitError):
            await client.send_message(PushoverMessage(message="x"))


@pytest.mark.asyncio
async def test_cancel_receipt(client) -> None:
    url = API_CANCEL_RECEIPT_URL.format(receipt="rcpt-1")
    with aioresponses() as m:
        m.post(url, payload={"status": 1, "request": "req-2"})
        result = await client.cancel_receipt("rcpt-1")
        assert result["status"] == 1


@pytest.mark.asyncio
async def test_cancel_by_tag(client) -> None:
    url = API_CANCEL_BY_TAG_URL.format(tag="garage-door")
    with aioresponses() as m:
        m.post(url, payload={"status": 1, "request": "req-3"})
        result = await client.cancel_by_tag("garage-door")
        assert result["status"] == 1


@pytest.mark.asyncio
async def test_get_receipt(client) -> None:
    url = API_RECEIPT_URL.format(receipt="rcpt-1")
    with aioresponses() as m:
        m.get(
            f"{url}?token={TOKEN}",
            payload={
                "status": 1,
                "acknowledged": 1,
                "acknowledged_at": 1700000000,
                "expired": 0,
            },
        )
        result = await client.get_receipt("rcpt-1")
        assert result["acknowledged"] == 1


@pytest.mark.asyncio
async def test_get_group_info(client) -> None:
    url = API_GROUP_URL.format(group=USER)
    with aioresponses() as m:
        m.get(
            f"{url}?token={TOKEN}",
            payload={
                "status": 1,
                "name": "Family",
                "users": [
                    {"user": "u1", "device": "phone", "memo": "Alice", "disabled": False},
                    {"user": "u2", "device": "tablet", "memo": "Bob", "disabled": False},
                ],
            },
        )
        result = await client.get_group_info()
        assert result["name"] == "Family"
        assert [u["device"] for u in result["users"]] == ["phone", "tablet"]


@pytest.mark.asyncio
async def test_get_group_info_not_a_group_raises(client) -> None:
    url = API_GROUP_URL.format(group=USER)
    with aioresponses() as m:
        m.get(
            f"{url}?token={TOKEN}",
            status=400,
            payload={"status": 0, "errors": ["group not found"]},
        )
        with pytest.raises(PushoverApiError):
            await client.get_group_info()


def test_encode_attachment_base64_round_trip() -> None:
    import base64

    data = b"some binary data \x00\x01"
    encoded = encode_attachment_base64(data)
    assert base64.b64decode(encoded) == data
