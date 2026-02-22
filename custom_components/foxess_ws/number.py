"""Number entities for FoxESS settings control."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_client import FoxESSOpenApiClient
from .button import SIGNAL_REFRESH
from .const import CONF_DEVICE_NAME, CONF_DEVICE_SN, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class FoxESSNumberDescription(NumberEntityDescription):
    """Describe a FoxESS number entity."""

    api_key: str


NUMBER_DESCRIPTIONS: tuple[FoxESSNumberDescription, ...] = (
    FoxESSNumberDescription(
        key="min_soc_on_grid",
        translation_key="min_soc_on_grid",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        api_key="MinSocOnGrid",
    ),
    FoxESSNumberDescription(
        key="export_limit",
        translation_key="export_limit",
        native_min_value=0,
        native_max_value=30000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        api_key="ExportLimit",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FoxESS number entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    api_client: FoxESSOpenApiClient = data["api_client"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    entities = [
        FoxESSNumberEntity(api_client, description, device_sn, device_name)
        for description in NUMBER_DESCRIPTIONS
    ]
    async_add_entities(entities)


class FoxESSNumberEntity(NumberEntity):
    """Number entity for FoxESS settings (MinSoc, MaxSoc, ExportLimit)."""

    entity_description: FoxESSNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        api_client: FoxESSOpenApiClient,
        description: FoxESSNumberDescription,
        device_sn: str,
        device_name: str,
    ) -> None:
        self._api_client = api_client
        self._device_sn = device_sn
        self.entity_description = description
        self._attr_unique_id = f"{device_sn}_{description.key}"
        self._attr_native_value: float | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"FoxESS {device_name}",
            manufacturer="FoxESS",
            model=device_name,
            serial_number=device_sn,
        )

    async def async_added_to_hass(self) -> None:
        """Fetch the current value when entity is added."""
        await super().async_added_to_hass()
        await self._fetch_value()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_REFRESH.format(self._device_sn),
                self._fetch_value,
            )
        )

    async def _fetch_value(self) -> None:
        """Read current value from the OpenAPI."""
        try:
            result = await self._api_client.get_setting(
                self._device_sn, self.entity_description.api_key
            )
            if isinstance(result, dict):
                self._attr_native_value = float(result.get("value", 0))
            else:
                self._attr_native_value = float(result)
            self.async_write_ha_state()
        except Exception:
            _LOGGER.warning(
                "Failed to read %s", self.entity_description.api_key
            )

    async def async_set_native_value(self, value: float) -> None:
        """Set the value via OpenAPI."""
        int_val = int(value)
        await self._api_client.set_setting(
            self._device_sn, self.entity_description.api_key, int_val
        )
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Set %s = %s on %s",
            self.entity_description.api_key,
            int_val,
            self._device_sn,
        )
