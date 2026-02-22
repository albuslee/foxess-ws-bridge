"""Switch entity for FoxESS scheduler enable/disable."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_client import FoxESSOpenApiClient
from .button import SIGNAL_REFRESH
from .const import CONF_DEVICE_NAME, CONF_DEVICE_SN, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FoxESS switch entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    api_client: FoxESSOpenApiClient = data["api_client"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    async_add_entities(
        [FoxESSSchedulerSwitch(api_client, device_sn, device_name)]
    )


class FoxESSSchedulerSwitch(SwitchEntity):
    """Switch to enable/disable the charge/discharge scheduler."""

    _attr_has_entity_name = True
    _attr_translation_key = "scheduler_enable"

    def __init__(
        self,
        api_client: FoxESSOpenApiClient,
        device_sn: str,
        device_name: str,
    ) -> None:
        self._api_client = api_client
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_scheduler_enable"
        self._attr_is_on: bool | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"FoxESS {device_name}",
            manufacturer="FoxESS",
            model=device_name,
            serial_number=device_sn,
        )

    async def async_added_to_hass(self) -> None:
        """Read current scheduler state when entity is added."""
        await super().async_added_to_hass()
        await self._fetch_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_REFRESH.format(self._device_sn),
                self._fetch_state,
            )
        )

    async def _fetch_state(self) -> None:
        """Read scheduler enabled state from the API."""
        try:
            enabled = await self._api_client.is_scheduler_enabled(self._device_sn)
            self._attr_is_on = enabled
            self.async_write_ha_state()
        except Exception:
            _LOGGER.warning("Failed to read scheduler state for %s", self._device_sn)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the scheduler. Groups are preserved on the server."""
        await self._api_client.toggle_scheduler(self._device_sn, enable=True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the scheduler. Groups are preserved on the server."""
        await self._api_client.toggle_scheduler(self._device_sn, enable=False)
        self._attr_is_on = False
        self.async_write_ha_state()
