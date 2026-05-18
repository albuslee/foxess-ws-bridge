"""Config flow for FoxESS WebSocket integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import FoxESSOpenApiClient, OpenApiError
from .auth import AuthenticationError, get_plants, load_wasm, login
from .const import (
    CONF_API_KEY,
    CONF_DEVICE_NAME,
    CONF_DEVICE_SN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_API_KEY): str,
    }
)


class FoxESSWSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FoxESS WebSocket."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str = ""
        self._password: str = ""
        self._api_key: str = ""
        self._token: str = ""
        self._plants: list[dict[str, Any]] = []
        self._devices: list[dict[str, Any]] = []
        self._get_signature: Any = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step — credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            self._api_key = user_input[CONF_API_KEY]

            session = async_get_clientsession(self.hass)

            # Validate web login (email + password)
            try:
                self._get_signature = await self.hass.async_add_executor_job(load_wasm)
                self._token = await login(
                    session,
                    self._get_signature,
                    self._email,
                    self._password,
                    self.hass.config.time_zone,
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during web login")
                errors["base"] = "cannot_connect"

            if not errors:
                # Validate OpenAPI key
                try:
                    api_client = FoxESSOpenApiClient(self._api_key, session)
                    self._devices = await api_client.get_device_list()
                except OpenApiError:
                    errors["base"] = "invalid_api_key"
                except Exception:
                    _LOGGER.exception("Unexpected error validating API key")
                    errors["base"] = "cannot_connect"

            if not errors:
                # Fetch plants for the device selection step
                try:
                    self._plants = await get_plants(
                        session,
                        self._get_signature,
                        self._token,
                        self.hass.config.time_zone,
                    )
                except Exception:
                    _LOGGER.exception("Failed to fetch plants")
                    # Non-fatal — we can still proceed with devices from OpenAPI

                if self._devices:
                    return await self.async_step_select_device()

                errors["base"] = "no_devices"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device selection step."""
        if user_input is not None:
            selected_sn = user_input[CONF_DEVICE_SN]

            # Find matching device and plant
            device = next((d for d in self._devices if d.get("deviceSN") == selected_sn), {})
            device_name = device.get("deviceType", selected_sn)

            # Try to match plant from the plant list
            plant_id = device.get("stationID", "")
            plant_name = ""
            for plant in self._plants:
                if plant.get("stationID") == plant_id:
                    plant_name = plant.get("name", "")
                    break

            await self.async_set_unique_id(selected_sn)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"FoxESS {device_name} ({selected_sn})",
                data={
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_API_KEY: self._api_key,
                    CONF_DEVICE_SN: selected_sn,
                    CONF_PLANT_ID: plant_id,
                    CONF_PLANT_NAME: plant_name,
                    CONF_DEVICE_NAME: device_name,
                },
            )

        # Build device dropdown
        device_options = {
            d["deviceSN"]: f"{d.get('deviceType', 'Unknown')} ({d['deviceSN']})"
            for d in self._devices
            if "deviceSN" in d
        }

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_SN): vol.In(device_options)}),
        )
