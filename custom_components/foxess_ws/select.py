"""Select entities for FoxESS work mode control."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_client import FoxESSOpenApiClient
from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SN,
    DOMAIN,
    SCHEDULER_WORK_MODES,
    WORK_MODES,
)
from .coordinator import FoxESSWSCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FoxESS select entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FoxESSWSCoordinator = data["coordinator"]
    api_client: FoxESSOpenApiClient = data["api_client"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    async_add_entities([FoxESSWorkModeSelect(coordinator, api_client, device_sn, device_name)])


class FoxESSWorkModeSelect(SelectEntity):
    """Select entity for inverter work mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "work_mode"
    # Include all modes so scheduler modes (ForceCharge, ForceDischarge) display correctly
    _attr_options = list(dict.fromkeys(WORK_MODES + SCHEDULER_WORK_MODES))

    def __init__(
        self,
        coordinator: FoxESSWSCoordinator,
        api_client: FoxESSOpenApiClient,
        device_sn: str,
        device_name: str,
    ) -> None:
        self._coordinator = coordinator
        self._api_client = api_client
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_work_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"FoxESS {device_name}",
            manufacturer="FoxESS",
            model=device_name,
            serial_number=device_sn,
        )

    @property
    def current_option(self) -> str | None:
        """Return current work mode from WebSocket data."""
        if self._coordinator.data is None:
            return None
        mode = self._coordinator.data.work_mode
        if not mode:
            return None
        if mode in self._attr_options:
            return mode
        _LOGGER.debug("Unknown work mode from WebSocket: %r", mode)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the work mode via OpenAPI."""
        await self._api_client.set_setting(self._device_sn, "WorkMode", option)
        _LOGGER.info("Work mode changed to %s", option)
