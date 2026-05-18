"""FoxESS Web API client — uses browser-style WASM auth for fast writes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .auth import _build_headers
from .const import (
    FOXESS_BASE_URL,
    WEBAPI_PLANT_DEVICES,
    WEBAPI_SCHEDULER_GET,
    WEBAPI_SCHEDULER_SET,
)

_LOGGER = logging.getLogger(__name__)


class WebApiError(Exception):
    """Raised when a FoxESS web API call fails."""


class FoxESSWebClient:
    """Client for FoxESS web API (browser-style auth, fast responses)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        get_signature: Callable[..., str],
        token_getter: Callable[[], str],
        device_id: str,
        tz: str = "UTC",
    ) -> None:
        self._session = session
        self._get_signature = get_signature
        self._get_token = token_getter
        self._device_id = device_id
        self._tz = tz

    def _headers(self, path: str) -> dict[str, str]:
        """Build authenticated headers for a web API request."""
        return _build_headers(path, self._get_token(), self._get_signature, self._tz)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Make an authenticated POST request to the web API."""
        url = f"{FOXESS_BASE_URL}{path}"
        headers = self._headers(path)
        headers["Origin"] = FOXESS_BASE_URL

        async with self._session.post(url, json=payload, headers=headers) as resp:
            data: dict[str, Any] = await resp.json()

        if data.get("errno") != 0:
            _LOGGER.error(
                "Web API error on %s: errno=%s, msg=%s",
                path,
                data.get("errno"),
                data.get("msg"),
            )
            raise WebApiError(f"Web API {path}: errno={data.get('errno')}, msg={data.get('msg')}")

        return data

    async def _get(self, path: str) -> dict[str, Any]:
        """Make an authenticated GET request to the web API."""
        url = f"{FOXESS_BASE_URL}{path}"
        headers = self._headers(path)

        async with self._session.get(url, headers=headers) as resp:
            data: dict[str, Any] = await resp.json()

        if data.get("errno") != 0:
            _LOGGER.error(
                "Web API error on %s: errno=%s, msg=%s",
                path,
                data.get("errno"),
                data.get("msg"),
            )
            raise WebApiError(f"Web API {path}: errno={data.get('errno')}, msg={data.get('msg')}")

        return data

    @staticmethod
    def _to_web_format(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAPI-style groups to web API flat format.

        OpenAPI: {workMode, extraParam: {fdSoc, fdPwr, minSocOnGrid, maxSoc}}
        Web API: {workMode, enable, fdsoc, fdpwr, minsocongrid, maxsoc}
        """
        web_groups = []
        for g in groups:
            extra = g.get("extraParam", {})
            web_groups.append(
                {
                    "enable": True,
                    "startHour": g["startHour"],
                    "startMinute": g["startMinute"],
                    "endHour": g["endHour"],
                    "endMinute": g["endMinute"],
                    "workMode": g["workMode"],
                    "minsocongrid": extra.get("minSocOnGrid", 10),
                    "fdsoc": extra.get("fdSoc", 10),
                    "fdpwr": extra.get("fdPwr", 6500),
                    "maxsoc": extra.get("maxSoc", 100),
                }
            )
        return web_groups

    async def set_scheduler(self, groups: list[dict[str, Any]]) -> None:
        """Write scheduler groups via the web API.

        Accepts groups in OpenAPI format (with extraParam nesting)
        and converts to the flat web API format automatically.
        """
        web_groups = self._to_web_format(groups)
        payload = {
            "schedulerList": web_groups,
            "deviceID": self._device_id,
            "currentShard": 1,
            "getShardSize": 1,
            "putShardSize": 1,
        }
        await self._post(WEBAPI_SCHEDULER_SET, payload)
        _LOGGER.info(
            "Web API: schedule updated on %s (%d groups)",
            self._device_id,
            len(groups),
        )

    async def get_scheduler(self) -> dict[str, Any]:
        """Read current scheduler via the web API."""
        data = await self._post(
            WEBAPI_SCHEDULER_GET,
            {"deviceID": self._device_id, "shardID": 1},
        )
        return data.get("result", {})

    async def update_peak_fdpwr(self, fdpwr: int, start_hour: int = 18, end_hour: int = 19) -> int:
        """Read current scheduler, update fdpwr on a matching discharge group, write back.

        Returns the number of groups matched and updated.
        """
        result = await self.get_scheduler()
        groups = result.get("schedulerList", [])
        if not groups:
            raise WebApiError("No scheduler groups found on device")

        updated = 0
        for g in groups:
            if g.get("startHour") == start_hour and g.get("endHour") == end_hour:
                g["fdpwr"] = fdpwr
                updated += 1

        if updated == 0:
            raise WebApiError(
                f"No {start_hour:02d}:00-{end_hour:02d}:59 group found in current scheduler"
            )

        payload = {
            "schedulerList": groups,
            "deviceID": self._device_id,
            "currentShard": 1,
            "getShardSize": 1,
            "putShardSize": 1,
        }
        await self._post(WEBAPI_SCHEDULER_SET, payload)
        _LOGGER.info(
            "Web API: updated fdpwr=%d on %d group(s) for %s",
            fdpwr,
            updated,
            self._device_id,
        )
        return updated


async def resolve_device_id(
    session: aiohttp.ClientSession,
    get_signature: Callable[..., str],
    token: str,
    plant_id: str,
    device_sn: str,
    tz: str = "UTC",
) -> str | None:
    """Resolve the web API deviceID (UUID) from plant_id and device_sn.

    Calls GET /dew/v0/plant/devices?plantID={plant_id} and matches by SN.
    Returns None if resolution fails (caller should skip web client).
    """
    query_path = f"{WEBAPI_PLANT_DEVICES}?plantID={plant_id}"
    url = f"{FOXESS_BASE_URL}{query_path}"
    # Sign with just the base path (no query string) — matches browser behaviour
    headers = _build_headers(WEBAPI_PLANT_DEVICES, token, get_signature, tz)
    # GET requests: replace Content-Type with the custom header the browser uses
    headers.pop("Content-Type", None)
    headers["contenttype"] = "application/json"

    _LOGGER.debug(
        "resolve_device_id: GET %s (signed path=%s)",
        query_path,
        WEBAPI_PLANT_DEVICES,
    )

    try:
        async with session.get(url, headers=headers) as resp:
            data: dict[str, Any] = await resp.json()

        if data.get("errno") != 0:
            _LOGGER.warning(
                "Failed to resolve deviceID: errno=%s, msg=%s",
                data.get("errno"),
                data.get("msg"),
            )
            return None

        devices = data.get("result", {}).get("device", [])
        for device in devices:
            if device.get("sn") == device_sn:
                device_id = device.get("id")
                _LOGGER.info(
                    "Resolved deviceID for %s: %s",
                    device_sn,
                    device_id,
                )
                return device_id

        _LOGGER.warning("Device SN %s not found in plant %s", device_sn, plant_id)
        return None

    except Exception:
        _LOGGER.warning("Failed to resolve deviceID", exc_info=True)
        return None
