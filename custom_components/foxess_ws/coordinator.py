"""WebSocket data coordinator for FoxESS real-time data."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import websockets
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from websockets.asyncio.client import ClientConnection

from .auth import AuthenticationError, build_ws_url, login, logout
from .const import (
    BATTERY_CHARGE_DISCHARGING,
    BATTERY_CHARGE_MAP,
    DOMAIN,
    TOKEN_EXPIRED_CODES,
    WS_KEEPALIVE_INTERVAL,
    WS_RECONNECT_CYCLE,
    WS_RECONNECT_MAX,
    WS_RECONNECT_MIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class FoxESSRealtimeData:
    """Parsed real-time data from WebSocket."""

    solar_power: float = 0.0
    grid_power: float = 0.0  # signed: positive=importing, negative=exporting
    battery_power: float = 0.0  # signed: positive=charging, negative=discharging
    battery_soc: int = 0
    battery_charge: str = "idle"  # idle, charging, discharging
    load_power: float = 0.0
    normal_load: float = 0.0
    backup_load: float = 0.0
    aux_power: float = 0.0
    grid_status: str = "idle"  # importing, exporting, idle
    time_flag: str = ""  # day, night
    work_mode: str = ""
    plant_status: int = 0
    device_sn: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _convert_to_watts(val: str | None, unit: str) -> float:
    """Convert a power value to watts, logging unknown units."""
    if val == "--" or val is None:
        return 0.0
    try:
        result = float(val)
    except (ValueError, TypeError):
        return 0.0
    if unit == "W":
        return result
    if unit == "kW":
        return result * 1000
    _LOGGER.warning("Unknown power unit '%s' with value '%s'", unit, val)
    return result


def _parse_power(node: dict[str, Any]) -> float:
    """Extract power value in watts from a node, returning 0.0 if unavailable."""
    power = node.get("power", {})
    return _convert_to_watts(power.get("value", "0"), power.get("unit", "W"))


def _parse_sub_power(node: dict[str, Any]) -> float:
    """Extract power in watts from a sub-node like normalLoad/backupLoad."""
    return _convert_to_watts(node.get("value", "0"), node.get("unit", "W"))


def parse_ws_message(msg: dict[str, Any]) -> FoxESSRealtimeData | None:
    """Parse a WebSocket message into FoxESSRealtimeData."""
    if msg.get("errno") != 0:
        return None

    result = msg.get("result", {})
    node = result.get("node", {})

    solar = node.get("solar", {})
    grid = node.get("grid", {})
    bat = node.get("bat", {})
    load = node.get("load", {})
    aux = node.get("aux", {})

    charge_val = bat.get("charge", 0)
    battery_charge = BATTERY_CHARGE_MAP.get(charge_val, "idle")

    # Sign battery power: positive = charging, negative = discharging
    bat_power = _parse_power(bat)
    if charge_val == BATTERY_CHARGE_DISCHARGING:
        bat_power = -bat_power

    # Sign grid power: positive = importing, negative = exporting
    # gridToHidden: -1 = exporting, 0 = idle, 1 = importing
    grid_power = _parse_power(grid)
    grid_to_hidden = grid.get("gridToHidden", 0)
    if grid_to_hidden == -1:
        grid_power = -grid_power
    if grid_to_hidden == -1:
        grid_status = "exporting"
    elif grid_to_hidden == 1:
        grid_status = "importing"
    else:
        grid_status = "idle"

    normal_load = _parse_sub_power(load.get("normalLoad", {}))
    backup_load = _parse_sub_power(load.get("backupLoad", {}))

    aux_power = _parse_power(aux)

    return FoxESSRealtimeData(
        solar_power=_parse_power(solar),
        grid_power=grid_power,
        battery_power=bat_power,
        battery_soc=bat.get("soc", 0),
        battery_charge=battery_charge,
        load_power=_parse_power(load),
        normal_load=normal_load,
        backup_load=backup_load,
        aux_power=aux_power,
        grid_status=grid_status,
        time_flag=result.get("timeFlag", ""),
        work_mode=result.get("workMode") or "",
        plant_status=result.get("plantStatus", 0),
        device_sn=result.get("sn", ""),
        raw=result,
    )


class FoxESSWSCoordinator(DataUpdateCoordinator[FoxESSRealtimeData]):
    """Manage WebSocket connection and push data to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        get_signature: Callable[..., str],
        email: str,
        password: str,
        plant_id: str,
        token: str,
        tz: str = "UTC",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_ws",
        )
        self._session = session
        self._get_signature = get_signature
        self._email = email
        self._password = password
        self._plant_id = plant_id
        self._token = token
        self._tz = tz
        self._ws: ClientConnection | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._reconnect_delay = WS_RECONNECT_MIN
        self._connected = False
        self._shutdown = False

    @property
    def connected(self) -> bool:
        """Return True if the WebSocket is connected."""
        return self._connected

    @property
    def token(self) -> str:
        """Return the current session token (for web API reuse)."""
        return self._token

    async def async_start(self) -> None:
        """Start the WebSocket connection loop."""
        self._shutdown = False
        self._listen_task = self.hass.async_create_background_task(
            self._connection_loop(), f"{DOMAIN}_ws_loop"
        )

    async def async_stop(self) -> None:
        """Stop the WebSocket connection."""
        self._shutdown = True
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._connected = False

    async def _connection_loop(self) -> None:
        """Main loop: connect, listen, reconnect on failure."""
        while not self._shutdown:
            try:
                await self._refresh_token()
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception:
                _LOGGER.exception("WebSocket connection error")

            if self._shutdown:
                break

            self._connected = False
            self.async_set_updated_data(self.data)  # notify sensors of disconnect

            _LOGGER.info("Reconnecting in %s seconds...", self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, WS_RECONNECT_MAX)

    async def _refresh_token(self) -> None:
        """Logout old session, then re-login to get a fresh token."""
        if self._token:
            await logout(self._session, self._get_signature, self._token, self._tz)
        try:
            self._token = await login(
                self._session,
                self._get_signature,
                self._email,
                self._password,
                self._tz,
            )
            _LOGGER.debug("Token refreshed")
        except AuthenticationError:
            _LOGGER.error("Failed to refresh token")
            raise

    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket and process incoming messages."""
        ws_url = build_ws_url(self._plant_id, self._token)
        _LOGGER.debug("Connecting to WebSocket...")

        # Create SSL context in executor to avoid blocking the event loop
        ssl_context = await self.hass.async_add_executor_job(ssl.create_default_context)

        async with websockets.connect(
            ws_url,
            additional_headers={"Origin": "https://www.foxesscloud.com"},
            ping_interval=None,  # We handle keepalive ourselves
            ssl=ssl_context,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._reconnect_delay = WS_RECONNECT_MIN
            _LOGGER.info("WebSocket connected")

            # Start keepalive
            self._keepalive_task = self.hass.async_create_background_task(
                self._keepalive(ws), f"{DOMAIN}_ws_keepalive"
            )

            # Schedule a forced reconnect to maintain ~5s server pushes
            reconnect_task = self.hass.async_create_background_task(
                self._force_reconnect(ws), f"{DOMAIN}_ws_reconnect"
            )

            try:
                async for raw_msg in ws:
                    if self._shutdown:
                        break
                    await self._handle_message(raw_msg)
            finally:
                if self._keepalive_task and not self._keepalive_task.done():
                    self._keepalive_task.cancel()
                if not reconnect_task.done():
                    reconnect_task.cancel()
                self._ws = None
                self._connected = False

    async def _keepalive(self, ws: ClientConnection) -> None:
        """Send keepalive messages every 30 seconds."""
        try:
            while not self._shutdown:
                await asyncio.sleep(WS_KEEPALIVE_INTERVAL)
                await ws.send("getdata")
                _LOGGER.debug("Sent keepalive")
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass

    async def _force_reconnect(self, ws: ClientConnection) -> None:
        """Close the connection after WS_RECONNECT_CYCLE to get fresh 5s pushes."""
        try:
            await asyncio.sleep(WS_RECONNECT_CYCLE)
            _LOGGER.info("Reconnect cycle reached, refreshing connection")
            await ws.close()
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass

    async def _handle_message(self, raw_msg: str | bytes) -> None:
        """Parse and process an incoming WebSocket message."""
        try:
            msg = json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning("Failed to parse WebSocket message")
            return

        errno = msg.get("errno", 0)

        # Token expired — re-login and reconnect
        if errno in TOKEN_EXPIRED_CODES:
            _LOGGER.warning("Token expired (errno=%s), re-authenticating...", errno)
            try:
                self._token = await login(
                    self._session,
                    self._get_signature,
                    self._email,
                    self._password,
                    self._tz,
                )
                _LOGGER.info("Re-authentication successful")
            except AuthenticationError:
                _LOGGER.error("Re-authentication failed")
            # Close the connection to trigger reconnect with new token
            if self._ws:
                await self._ws.close()
            return

        if errno != 0:
            _LOGGER.warning("WebSocket error: errno=%s, msg=%s", errno, msg.get("msg"))
            return

        data = parse_ws_message(msg)
        if data is not None:
            self.async_set_updated_data(data)

    async def _async_update_data(self) -> FoxESSRealtimeData:
        """Not used — data is pushed via WebSocket, not polled."""
        return self.data or FoxESSRealtimeData()
