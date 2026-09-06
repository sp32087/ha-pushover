"""Tests for the shared live device/sound lookup helpers in discovery.py."""
from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.pushover_advanced.api import PushoverClient
from custom_components.pushover_advanced.const import (
    API_GROUP_URL,
    API_VALIDATE_URL,
    KNOWN_SOUNDS,
)
from custom_components.pushover_advanced.discovery import (
    fetch_known_devices,
    fetch_known_sounds,
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


@pytest.mark.asyncio
async def test_fetch_known_devices_merges_user_and_group_devices(client) -> None:
    with aioresponses() as m:
        m.post(API_VALIDATE_URL, payload={"status": 1, "devices": ["phone"]})
        m.get(
            f"{API_GROUP_URL.format(group=USER)}?token={TOKEN}",
            payload={
                "status": 1,
                "users": [
                    {"device": "phone"},  # duplicate of the user's own device
                    {"device": "tablet"},
                ],
            },
        )
        devices = await fetch_known_devices(client)

    assert devices == ["phone", "tablet"]


@pytest.mark.asyncio
async def test_fetch_known_devices_survives_both_calls_failing(client) -> None:
    with aioresponses() as m:
        m.post(API_VALIDATE_URL, status=400, payload={"status": 0, "errors": ["bad token"]})
        m.get(
            f"{API_GROUP_URL.format(group=USER)}?token={TOKEN}",
            status=400,
            payload={"status": 0, "errors": ["not a group"]},
        )
        devices = await fetch_known_devices(client)

    assert devices == []


@pytest.mark.asyncio
async def test_fetch_known_sounds_returns_live_catalog(client) -> None:
    from custom_components.pushover_advanced.const import API_SOUNDS_URL

    with aioresponses() as m:
        m.get(
            f"{API_SOUNDS_URL}?token={TOKEN}",
            payload={"status": 1, "sounds": {"pushover": "Pushover (default)", "siren": "Siren"}},
        )
        options = await fetch_known_sounds(client)

    assert {"value": "pushover", "label": "pushover — Pushover (default)"} in options
    assert {"value": "siren", "label": "siren — Siren"} in options


@pytest.mark.asyncio
async def test_fetch_known_sounds_falls_back_when_unreachable(client) -> None:
    from custom_components.pushover_advanced.const import API_SOUNDS_URL

    with aioresponses() as m:
        m.get(f"{API_SOUNDS_URL}?token={TOKEN}", exception=aiohttp.ClientConnectionError())
        options = await fetch_known_sounds(client)

    assert [o["value"] for o in options] == KNOWN_SOUNDS
