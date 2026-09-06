"""Config and options flow for Pushover Advanced."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import PushoverClient
from .const import (
    CONF_API_TOKEN,
    CONF_DEFAULT_DEVICE,
    CONF_DEFAULT_EXPIRE,
    CONF_DEFAULT_PRIORITY,
    CONF_DEFAULT_RETRY,
    CONF_DEFAULT_SOUND,
    CONF_DEFAULT_TTL,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_ENCRYPTION_KEY,
    CONF_USER_KEY,
    DOMAIN,
    KNOWN_SOUNDS,
    MAX_EXPIRE_SECONDS,
    MIN_RETRY_SECONDS,
)
from .crypto import self_test
from .exceptions import PushoverAuthError, PushoverEncryptionError, PushoverError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Pushover"): TextSelector(),
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_USER_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


async def _validate_credentials(hass, api_token: str, user_key: str) -> None:
    session = async_get_clientsession(hass)
    client = PushoverClient(session, api_token, user_key)
    await client.validate_user()


async def _fetch_known_devices(client: PushoverClient) -> list[str]:
    """Return the device names Pushover knows about for this user or group key.

    For a plain user key, /users/validate.json lists that user's own
    devices. For a *group* key, the same call doesn't enumerate members, so
    we also try the /groups/ endpoint, which lists each member's device and
    succeeds only when user_key is actually a group key. Either call can
    legitimately fail (e.g. a user key isn't a group), so failures are
    swallowed rather than surfaced - this is a best-effort convenience list,
    not a required step.
    """
    device_names: list[str] = []

    try:
        validate_result = await client.validate_user()
    except (PushoverError, aiohttp.ClientError, TimeoutError):
        validate_result = {}
    device_names.extend(validate_result.get("devices", []))

    try:
        group_result = await client.get_group_info()
    except (PushoverError, aiohttp.ClientError, TimeoutError):
        group_result = {}
    for member in group_result.get("users", []):
        device = member.get("device")
        if device:
            device_names.append(device)

    # De-duplicate while preserving order.
    return list(dict.fromkeys(device_names))


async def _fetch_known_sounds(client: PushoverClient) -> list[SelectOptionDict]:
    """Return the current Pushover sound catalog as select options.

    Falls back to the last known-good hardcoded list if the API call fails
    (e.g. offline), so the form still works, just without descriptions.
    """
    try:
        sounds = await client.get_sounds()
    except (PushoverError, aiohttp.ClientError, TimeoutError):
        return [SelectOptionDict(value=sound, label=sound) for sound in KNOWN_SOUNDS]

    return [
        SelectOptionDict(value=key, label=f"{key} — {description}")
        for key, description in sounds.items()
    ]


class PushoverAdvancedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle creation of a Pushover Advanced config entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect the application token and user/group key, then validate them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_API_TOKEN]}:{user_input[CONF_USER_KEY]}"
            )
            self._abort_if_unique_id_configured()

            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_API_TOKEN], user_input[CONF_USER_KEY]
                )
            except PushoverAuthError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except PushoverError:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
                        CONF_USER_KEY: user_input[CONF_USER_KEY],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PushoverAdvancedOptionsFlow:
        """Get the options flow for this handler."""
        return PushoverAdvancedOptionsFlow()


class PushoverAdvancedOptionsFlow(config_entries.OptionsFlow):
    """Manage per-device encryption secrets and sending defaults."""

    def _client(self) -> PushoverClient:
        session = async_get_clientsession(self.hass)
        return PushoverClient(
            session,
            self.config_entry.data[CONF_API_TOKEN],
            self.config_entry.data[CONF_USER_KEY],
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Offer the menu of things that can be configured."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["defaults", "add_device", "remove_device"],
        )

    async def async_step_defaults(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Set the defaults used when a service call doesn't override them."""
        current = self.config_entry.options
        configured_devices = current.get(CONF_DEVICES, {})

        client = self._client()
        live_devices = await _fetch_known_devices(client)
        sound_options = await _fetch_known_sounds(client)

        # Merge live account devices with ones we already have encryption
        # keys for (in case the account lookup failed or a device was
        # removed from the account since), preserving order, then dedupe.
        device_names = list(dict.fromkeys(["", *live_devices, *configured_devices.keys()]))

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEFAULT_DEVICE, default=current.get(CONF_DEFAULT_DEVICE, "")
                ): SelectSelector(
                    SelectSelectorConfig(options=device_names, custom_value=True)
                ),
                vol.Optional(
                    CONF_DEFAULT_PRIORITY, default=current.get(CONF_DEFAULT_PRIORITY, 0)
                ): NumberSelector(
                    NumberSelectorConfig(min=-2, max=2, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_DEFAULT_SOUND, default=current.get(CONF_DEFAULT_SOUND, "pushover")
                ): SelectSelector(
                    SelectSelectorConfig(options=sound_options, custom_value=True)
                ),
                vol.Optional(
                    CONF_DEFAULT_TTL, default=current.get(CONF_DEFAULT_TTL, 0)
                ): NumberSelector(NumberSelectorConfig(min=0, max=2678400, step=1)),
                vol.Optional(
                    CONF_DEFAULT_RETRY, default=current.get(CONF_DEFAULT_RETRY, 60)
                ): NumberSelector(
                    NumberSelectorConfig(min=MIN_RETRY_SECONDS, max=MAX_EXPIRE_SECONDS, step=1)
                ),
                vol.Optional(
                    CONF_DEFAULT_EXPIRE, default=current.get(CONF_DEFAULT_EXPIRE, 3600)
                ): NumberSelector(
                    NumberSelectorConfig(min=MIN_RETRY_SECONDS, max=MAX_EXPIRE_SECONDS, step=1)
                ),
            }
        )

        if user_input is not None:
            new_options = dict(current)
            new_options.update(user_input)
            if not new_options.get(CONF_DEFAULT_DEVICE):
                new_options.pop(CONF_DEFAULT_DEVICE, None)
            return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(step_id="defaults", data_schema=schema)

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add (or replace) a device's end-to-end encryption secret.

        The secret is the 64-character hex key shown in the Pushover app
        once end-to-end encryption is turned on for that device; it must
        match exactly or the device will be unable to decrypt anything
        this integration sends it.
        """
        errors: dict[str, str] = {}

        live_devices = await _fetch_known_devices(self._client())
        device_name_selector = (
            SelectSelector(SelectSelectorConfig(options=live_devices, custom_value=True))
            if live_devices
            else TextSelector()
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME): device_name_selector,
                vol.Required(CONF_ENCRYPTION_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        if user_input is not None:
            key_hex = user_input[CONF_ENCRYPTION_KEY].strip()
            try:
                key_is_valid = self_test(key_hex)
            except PushoverEncryptionError:
                key_is_valid = False

            if not key_is_valid:
                errors["base"] = "invalid_key_format"
            else:
                devices = dict(self.config_entry.options.get(CONF_DEVICES, {}))
                devices[user_input[CONF_DEVICE_NAME]] = {CONF_ENCRYPTION_KEY: key_hex}
                new_options = dict(self.config_entry.options)
                new_options[CONF_DEVICES] = devices
                return self.async_create_entry(title="", data=new_options)

        return self.async_show_form(
            step_id="add_device", data_schema=schema, errors=errors
        )

    async def async_step_remove_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Remove a previously configured device encryption secret."""
        devices = dict(self.config_entry.options.get(CONF_DEVICES, {}))

        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            devices.pop(user_input[CONF_DEVICE_NAME], None)
            new_options = dict(self.config_entry.options)
            new_options[CONF_DEVICES] = devices
            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME): SelectSelector(
                    SelectSelectorConfig(options=list(devices.keys()))
                )
            }
        )
        return self.async_show_form(step_id="remove_device", data_schema=schema)
