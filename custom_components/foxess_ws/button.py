"""Button entities for FoxESS actions."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_client import FoxESSOpenApiClient
from .const import CONF_DEVICE_NAME, CONF_DEVICE_SN, DOMAIN
from .coordinator import FoxESSWSCoordinator

_LOGGER = logging.getLogger(__name__)

SIGNAL_REFRESH = f"{DOMAIN}_refresh_{{}}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FoxESS button entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FoxESSWSCoordinator = data["coordinator"]
    api_client: FoxESSOpenApiClient = data["api_client"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_sn)},
        name=f"FoxESS {device_name}",
        manufacturer="FoxESS",
        model=device_name,
        serial_number=device_sn,
    )

    async_add_entities(
        [
            FoxESSRefreshButton(coordinator, api_client, device_sn, device_info),
            FoxESSReadSettingsButton(api_client, device_sn, device_info),
            FoxESSTestSchedulerButton(api_client, device_sn, device_info),
        ]
    )


class FoxESSRefreshButton(ButtonEntity):
    """Button to force a full data refresh (WebSocket + API settings)."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"

    def __init__(
        self,
        coordinator: FoxESSWSCoordinator,
        api_client: FoxESSOpenApiClient,
        device_sn: str,
        device_info: DeviceInfo,
    ) -> None:
        self._coordinator = coordinator
        self._api_client = api_client
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_refresh"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """Force refresh: WebSocket data + API settings/scheduler."""
        # Refresh WebSocket sensor data
        if self._coordinator._ws is not None:
            await self._coordinator._ws.send("getdata")
            _LOGGER.debug("Sent WebSocket refresh")

        # Signal number/switch entities to re-read from API
        async_dispatcher_send(self.hass, SIGNAL_REFRESH.format(self._device_sn))
        _LOGGER.debug("Sent API refresh signal for %s", self._device_sn)


class FoxESSReadSettingsButton(ButtonEntity):
    """Button to read current settings from OpenAPI."""

    _attr_has_entity_name = True
    _attr_translation_key = "read_settings"

    def __init__(
        self,
        api_client: FoxESSOpenApiClient,
        device_sn: str,
        device_info: DeviceInfo,
    ) -> None:
        self._api_client = api_client
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_read_settings"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """Read all current settings and scheduler, then fire an event."""
        settings = await self._api_client.get_all_settings(self._device_sn)
        _LOGGER.info("Current settings for %s: %s", self._device_sn, settings)

        try:
            scheduler = await self._api_client.get_scheduler(self._device_sn)
            _LOGGER.info("Current scheduler for %s: %s", self._device_sn, scheduler)
        except Exception:
            _LOGGER.warning("Failed to read scheduler for %s", self._device_sn)
            scheduler = {}

        self.hass.bus.async_fire(
            f"{DOMAIN}_settings_read",
            {"device_sn": self._device_sn, "settings": settings, "scheduler": scheduler},
        )


class FoxESSTestSchedulerButton(ButtonEntity):
    """Button to test scheduler write by round-tripping current groups."""

    _attr_has_entity_name = True
    _attr_translation_key = "test_scheduler"

    def __init__(
        self,
        api_client: FoxESSOpenApiClient,
        device_sn: str,
        device_info: DeviceInfo,
    ) -> None:
        self._api_client = api_client
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_test_scheduler"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """Read current scheduler groups, write them back, verify."""
        # Step 1: Read current groups
        before = await self._api_client.get_scheduler(self._device_sn)
        groups = before.get("groups", [])
        _LOGGER.info("Test scheduler: read %d groups from %s", len(groups), self._device_sn)

        # Step 2: Write same groups back
        await self._api_client.set_scheduler(self._device_sn, groups)
        _LOGGER.info("Test scheduler: wrote %d groups back", len(groups))

        # Step 3: Read again to verify
        after = await self._api_client.get_scheduler(self._device_sn)
        after_groups = after.get("groups", [])
        _LOGGER.info("Test scheduler: verified %d groups after write", len(after_groups))

        if len(groups) == len(after_groups):
            _LOGGER.info("Test scheduler: PASSED — round-trip successful")
        else:
            _LOGGER.error(
                "Test scheduler: FAILED — wrote %d groups, read back %d",
                len(groups),
                len(after_groups),
            )
