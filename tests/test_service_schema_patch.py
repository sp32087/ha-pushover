"""Tests for the live device/sound select-menu patching of send_message.

services.yaml ships plain text fields for device and sound; __init__.py
patches copies of that static schema with select selectors built from an
account's live data so the frontend renders an actual dropdown. See
_patch_send_message_schema and _load_send_message_schema in __init__.py.
"""
from __future__ import annotations

from custom_components.pushover_advanced import (
    _load_send_message_schema,
    _patch_send_message_schema,
)
from custom_components.pushover_advanced.const import ATTR_DEVICE, ATTR_SOUND


def test_load_send_message_schema_reads_real_services_yaml() -> None:
    schema = _load_send_message_schema()
    assert schema is not None
    assert ATTR_DEVICE in schema["fields"]
    assert ATTR_SOUND in schema["fields"]


def test_patch_replaces_device_and_sound_with_select_selectors() -> None:
    base = _load_send_message_schema()
    patched = _patch_send_message_schema(
        base,
        device_names=["iphone", "desktop"],
        sound_options=[{"value": "pushover", "label": "pushover — Pushover (default)"}],
    )

    device_selector = patched["fields"][ATTR_DEVICE]["selector"]
    assert device_selector == {
        "select": {"options": ["iphone", "desktop"], "multiple": True, "custom_value": True}
    }

    sound_selector = patched["fields"][ATTR_SOUND]["selector"]
    assert sound_selector == {
        "select": {
            "options": [{"value": "pushover", "label": "pushover — Pushover (default)"}],
            "custom_value": True,
        }
    }


def test_patch_leaves_original_schema_untouched() -> None:
    base = _load_send_message_schema()
    original_device_selector = base["fields"][ATTR_DEVICE]["selector"]

    _patch_send_message_schema(base, device_names=["iphone"], sound_options=[])

    assert base["fields"][ATTR_DEVICE]["selector"] == original_device_selector


def test_patch_leaves_fields_untouched_when_no_live_data() -> None:
    base = _load_send_message_schema()
    original_device_selector = base["fields"][ATTR_DEVICE]["selector"]
    original_sound_selector = base["fields"][ATTR_SOUND]["selector"]

    patched = _patch_send_message_schema(base, device_names=[], sound_options=[])

    assert patched["fields"][ATTR_DEVICE]["selector"] == original_device_selector
    assert patched["fields"][ATTR_SOUND]["selector"] == original_sound_selector


def test_patch_preserves_other_field_descriptions() -> None:
    base = _load_send_message_schema()
    patched = _patch_send_message_schema(base, device_names=["iphone"], sound_options=[])

    assert patched["fields"]["message"] == base["fields"]["message"]
    assert patched["description"] == base["description"]
