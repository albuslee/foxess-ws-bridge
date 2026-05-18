"""Binary sensor for FoxESS WebSocket connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, CONF_DEVICE_SN, DOMAIN
from .coordinator import FoxESSWSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WebSocket connectivity binary sensor."""
    coordinator: FoxESSWSCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    async_add_entities([FoxESSConnectivitySensor(coordinator, device_sn, device_name)])


class FoxESSConnectivitySensor(CoordinatorEntity[FoxESSWSCoordinator], BinarySensorEntity):
    """Binary sensor indicating WebSocket connection status."""

    _attr_has_entity_name = True
    _attr_translation_key = "websocket_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: FoxESSWSCoordinator,
        device_sn: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{device_sn}_ws_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"FoxESS {device_name}",
            manufacturer="FoxESS",
            model=device_name,
            serial_number=device_sn,
        )

    @property
    def is_on(self) -> bool:
        """Return True if WebSocket is connected."""
        return self.coordinator.connected
