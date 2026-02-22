"""FoxESS OpenAPI client for write/control operations."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import aiohttp

from .const import (
    FOXESS_OPENAPI_BASE,
    OPENAPI_DEVICE_LIST,
    OPENAPI_SCHEDULER_ENABLE,
    OPENAPI_SCHEDULER_FLAG_SET,
    OPENAPI_SCHEDULER_GET,
    OPENAPI_SETTING_GET,
    OPENAPI_SETTING_SET,
)

_LOGGER = logging.getLogger(__name__)


class FoxESSOpenApiClient:
    """Client for FoxESS OpenAPI (control/write operations)."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    def _sign(self, path: str) -> tuple[str, str]:
        """Generate MD5 signature and timestamp for a request.

        The signature is md5("{path}\\r\\n{api_key}\\r\\n{timestamp}")
        where \\r\\n are the literal characters, not CRLF.
        """
        timestamp = str(int(time.time() * 1000))
        sig_text = f"{path}\\r\\n{self._api_key}\\r\\n{timestamp}"
        signature = hashlib.md5(sig_text.encode()).hexdigest()
        return signature, timestamp

    def _headers(self, path: str) -> dict[str, str]:
        """Build authenticated headers for an OpenAPI request."""
        signature, timestamp = self._sign(path)
        return {
            "Content-Type": "application/json",
            "Token": self._api_key,
            "Signature": signature,
            "Timestamp": timestamp,
            "Lang": "en",
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Make an authenticated POST request to the OpenAPI."""
        url = f"{FOXESS_OPENAPI_BASE}{path}"
        headers = self._headers(path)

        async with self._session.post(url, json=payload, headers=headers) as resp:
            data: dict[str, Any] = await resp.json()

        if data.get("errno") != 0:
            _LOGGER.error(
                "OpenAPI error on %s: errno=%s, msg=%s",
                path,
                data.get("errno"),
                data.get("msg"),
            )
            raise OpenApiError(
                f"OpenAPI {path}: errno={data.get('errno')}, msg={data.get('msg')}"
            )

        return data

    # --- Read methods ---

    async def get_device_list(self) -> list[dict[str, Any]]:
        """Fetch list of inverter devices."""
        data = await self._post(
            OPENAPI_DEVICE_LIST, {"currentPage": 1, "pageSize": 100}
        )
        return data.get("result", {}).get("data", [])

    async def get_setting(self, sn: str, key: str) -> Any:
        """Read a single device setting."""
        data = await self._post(OPENAPI_SETTING_GET, {"sn": sn, "key": key})
        return data.get("result", {})

    async def get_all_settings(self, sn: str) -> dict[str, Any]:
        """Read multiple commonly-used settings."""
        keys = ["WorkMode", "MinSocOnGrid", "ExportLimit"]
        results = {}
        for key in keys:
            try:
                results[key] = await self.get_setting(sn, key)
            except OpenApiError:
                _LOGGER.warning("Failed to read setting %s", key)
        return results

    async def get_scheduler(self, sn: str) -> dict[str, Any]:
        """Get the current charge/discharge schedule."""
        data = await self._post(OPENAPI_SCHEDULER_GET, {"deviceSN": sn})
        return data.get("result", {})

    # --- Write methods ---

    async def set_setting(self, sn: str, key: str, value: Any) -> None:
        """Change a device setting (WorkMode, MinSocOnGrid, ExportLimit, etc.).

        Note: This will fail with errno 44098 if the scheduler is active.
        Disable the scheduler first via the switch entity before writing.
        """
        await self._post(OPENAPI_SETTING_SET, {"sn": sn, "key": key, "value": value})
        _LOGGER.info("Set %s = %s on %s", key, value, sn)

    async def is_scheduler_enabled(self, sn: str) -> bool:
        """Check if the scheduler is currently enabled."""
        scheduler = await self.get_scheduler(sn)
        return bool(scheduler.get("enable"))

    async def toggle_scheduler(self, sn: str, enable: bool) -> None:
        """Enable or disable the scheduler without touching groups.

        Uses /op/v1/device/scheduler/set/flag to toggle the scheduler flag.
        Groups are preserved on the server regardless of enable state.
        """
        await self._post(
            OPENAPI_SCHEDULER_FLAG_SET,
            {"deviceSN": sn, "enable": 1 if enable else 0},
        )
        _LOGGER.info("Scheduler %s on %s", "enabled" if enable else "disabled", sn)

    async def set_scheduler(self, sn: str, groups: list[dict[str, Any]]) -> None:
        """Write charge/discharge schedule time slots.

        This overwrites ALL existing schedule groups on the inverter.
        Uses /op/v1/device/scheduler/enable which handles both
        enable/disable and group configuration.
        """
        await self._post(
            OPENAPI_SCHEDULER_ENABLE, {"deviceSN": sn, "groups": groups}
        )
        _LOGGER.info("Schedule updated on %s: %s", sn, groups)


class OpenApiError(Exception):
    """Raised when an OpenAPI call fails."""
