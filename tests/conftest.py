"""Test bootstrap.

These tests exercise custom_components/pushover_advanced/api.py and
crypto.py directly - plain Python with no Home Assistant runtime
dependency. But importing any submodule of a package first executes that
package's __init__.py, and this integration's __init__.py imports real
Home Assistant modules. Installing the full `homeassistant` PyPI package
just to satisfy that import pulls in a large, unrelated dependency tree
(and fails to build in this sandbox), so instead we register minimal
stand-in modules for the handful of Home Assistant symbols referenced at
import time, before anything under custom_components is imported.

This stub is intentionally tiny: it only needs to make `import
custom_components.pushover_advanced` succeed, not behave correctly - the
actual integration code (__init__.py, config_flow.py, notify.py) is not
exercised by this test suite.
"""
from __future__ import annotations

import sys
import types


def _install_homeassistant_stub() -> None:
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # noqa: D101 - stub
        pass

    class ConfigFlow:  # noqa: D101 - stub
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    class OptionsFlow:  # noqa: D101 - stub
        pass

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigFlowResult = dict

    const = types.ModuleType("homeassistant.const")

    class Platform:  # noqa: D101 - stub
        NOTIFY = "notify"

    const.Platform = Platform
    const.CONF_NAME = "name"

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D101 - stub
        pass

    class ServiceCall:  # noqa: D101 - stub
        pass

    class SupportsResponse:  # noqa: D101 - stub
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

    class ConfigEntryNotReady(Exception):  # noqa: D101 - stub
        pass

    class HomeAssistantError(Exception):  # noqa: D101 - stub
        pass

    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    exceptions.HomeAssistantError = HomeAssistantError

    helpers = types.ModuleType("homeassistant.helpers")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    for name in ("string", "boolean", "url", "isfile", "ensure_list"):
        setattr(config_validation, name, lambda value: value)

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
