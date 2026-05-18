"""Sensor entities for FoxESS WebSocket integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, CONF_DEVICE_SN, DOMAIN
from .coordinator import FoxESSRealtimeData, FoxESSWSCoordinator


@dataclass(frozen=True, kw_only=True)
class FoxESSSensorDescription(SensorEntityDescription):
    """Describe a FoxESS sensor."""

    value_fn: Callable[[FoxESSRealtimeData], Any]


SENSOR_DESCRIPTIONS: tuple[FoxESSSensorDescription, ...] = (
    FoxESSSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.solar_power,
    ),
    FoxESSSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.grid_power,
    ),
    FoxESSSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_power,
    ),
    FoxESSSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_soc,
    ),
    FoxESSSensorDescription(
        key="load_power",
        translation_key="load_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.load_power,
    ),
    FoxESSSensorDescription(
        key="normal_load",
        translation_key="normal_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.normal_load,
    ),
    FoxESSSensorDescription(
        key="backup_load",
        translation_key="backup_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.backup_load,
    ),
    FoxESSSensorDescription(
        key="aux_power",
        translation_key="aux_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.aux_power,
    ),
    FoxESSSensorDescription(
        key="battery_charge",
        translation_key="battery_charge",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "charging", "discharging"],
        value_fn=lambda d: d.battery_charge,
    ),
    FoxESSSensorDescription(
        key="grid_status",
        translation_key="grid_status",
        device_class=SensorDeviceClass.ENUM,
        options=["importing", "exporting", "idle"],
        value_fn=lambda d: d.grid_status,
    ),
    FoxESSSensorDescription(
        key="time_flag",
        translation_key="time_flag",
        value_fn=lambda d: d.time_flag,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FoxESS sensors from a config entry."""
    coordinator: FoxESSWSCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_sn = entry.data[CONF_DEVICE_SN]
    device_name = entry.data.get(CONF_DEVICE_NAME, device_sn)

    entities = [
        FoxESSSensor(coordinator, description, device_sn, device_name)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class FoxESSSensor(CoordinatorEntity[FoxESSWSCoordinator], SensorEntity):
    """A FoxESS sensor entity backed by WebSocket data."""

    entity_description: FoxESSSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FoxESSWSCoordinator,
        description: FoxESSSensorDescription,
        device_sn: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{device_sn}_{description.key}"
        self._device_sn = device_sn
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"FoxESS {device_name}",
            manufacturer="FoxESS",
            model=device_name,
            serial_number=device_sn,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
