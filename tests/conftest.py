"""Test bootstrap.

These tests exercise custom_components/pushover_advanced directly - plain
Python logic (api.py, crypto.py, the SEND_MESSAGE_SCHEMA validators and
_maybe_encrypt in __init__.py) with no running Home Assistant instance.
But importing any submodule of a package first executes that package's
__init__.py, and this integration's __init__.py imports real Home
Assistant modules. Installing the full `homeassistant` PyPI package just
to satisfy that import pulls in a large, unrelated dependency tree (and
fails to build in this sandbox), so instead we register minimal stand-in
modules for the handful of Home Assistant symbols referenced at import
time, before anything under custom_components is imported.

The config_validation (`cv`) stand-ins are written to actually validate
(reject a malformed URL, a non-boolean, etc.) so that SEND_MESSAGE_SCHEMA's
own tests are meaningful; everything else here only needs to exist, not
behave correctly - config_flow.py and notify.py are not exercised by this
test suite.
"""
from __future__ import annotations

import os
import sys
import types
import urllib.parse

import voluptuous


def _install_homeassistant_stub() -> None:
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        pass

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    class OptionsFlow:
        pass

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigFlowResult = dict

    const = types.ModuleType("homeassistant.const")

    class Platform:
        NOTIFY = "notify"

    const.Platform = Platform
    const.CONF_NAME = "name"

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    class ServiceCall:
        pass

    class SupportsResponse:
        NONE = "none"
        OPTIONAL = "optional"
        ONLY = "only"

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.ServiceCall = ServiceCall
    core.ServiceResponse = dict
    core.SupportsResponse = SupportsResponse
    core.callback = callback

    exceptions = types.ModuleType("homeassistant.exceptions")

    class ConfigEntryNotReady(Exception):
        pass

    class HomeAssistantError(Exception):
        pass

    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    exceptions.HomeAssistantError = HomeAssistantError

    helpers = types.ModuleType("homeassistant.helpers")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")

    # These mirror homeassistant.helpers.config_validation closely enough for
    # SEND_MESSAGE_SCHEMA's own tests to exercise real rejection behavior
    # (e.g. a malformed URL), rather than the no-op passthrough a plain
    # `lambda value: value` stub would give every field.
    def _cv_string(value):
        if not isinstance(value, str):
            raise voluptuous.Invalid("expected a string")
        return value

    def _cv_boolean(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no", "on", "off", "1", "0"):
            return value.lower() in ("true", "yes", "on", "1")
        raise voluptuous.Invalid("expected a boolean")

    def _cv_url(value):
        parsed = urllib.parse.urlparse(str(value))
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return str(value)
        raise voluptuous.Invalid(f"invalid url: {value}")

    def _cv_isfile(value):
        if not isinstance(value, str) or not os.path.isfile(value):
            raise voluptuous.Invalid(f"not a file: {value}")
        return value

    def _cv_ensure_list(value):
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    config_validation.string = _cv_string
    config_validation.boolean = _cv_boolean
    config_validation.url = _cv_url
    config_validation.isfile = _cv_isfile
    config_validation.ensure_list = _cv_ensure_list

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None

    helpers.config_validation = config_validation
    helpers.aiohttp_client = aiohttp_client

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.config_validation": config_validation,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
    }
    sys.modules.update(modules)


_install_homeassistant_stub()
