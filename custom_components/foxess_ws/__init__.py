"""FoxESS WebSocket integration for Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import FoxESSOpenApiClient
from .auth import load_wasm, login
from .const import (
    CONF_API_KEY,
    CONF_DEVICE_SN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PLANT_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import FoxESSWSCoordinator
from .web_client import FoxESSWebClient, resolve_device_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FoxESS WebSocket from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    api_key = entry.data[CONF_API_KEY]
    plant_id = entry.data[CONF_PLANT_ID]
    device_sn = entry.data[CONF_DEVICE_SN]

    session = async_get_clientsession(hass)
    tz = hass.config.time_zone

    # Load WASM signature module (blocking I/O — run in executor)
    get_signature = await hass.async_add_executor_job(load_wasm)

    # Login to get WebSocket token
    token = await login(session, get_signature, email, password, tz)

    # Create OpenAPI client for control operations (fallback)
    api_client = FoxESSOpenApiClient(api_key, session)

    # Resolve web API deviceID and create web client (fast path)
    web_client: FoxESSWebClient | None = None
    device_id = await resolve_device_id(
        session,
        get_signature,
        token,
        plant_id,
        device_sn,
        tz,
    )
    if device_id:
        # Create WebSocket coordinator first so we can reference its token
        coordinator = FoxESSWSCoordinator(
            hass=hass,
            session=session,
            get_signature=get_signature,
            email=email,
            password=password,
            plant_id=plant_id,
            token=token,
            tz=tz,
        )
        web_client = FoxESSWebClient(
            session=session,
            get_signature=get_signature,
            token_getter=lambda: coordinator.token,
            device_id=device_id,
            tz=tz,
        )
    else:
        _LOGGER.warning(
            "Could not resolve deviceID for %s — web API writes disabled, using OpenAPI only",
            device_sn,
        )
        coordinator = FoxESSWSCoordinator(
            hass=hass,
            session=session,
            get_signature=get_signature,
            email=email,
            password=password,
            plant_id=plant_id,
            token=token,
            tz=tz,
        )

    # Store references
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
        "web_client": web_client,
        "get_signature": get_signature,
    }

    # Forward platform setup
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start the WebSocket connection
    await coordinator.async_start()

    # --- Register domain services (once, guarded) ---
    if not hass.services.has_service(DOMAIN, "set_scheduler"):

        def _resolve_clients(sn: str) -> tuple[FoxESSOpenApiClient, FoxESSWebClient | None, str]:
            """Find api_client, web_client, and resolved SN for a service call."""
            api: FoxESSOpenApiClient | None = None
            web: FoxESSWebClient | None = None
            resolved_sn = sn
            for eid, entry_data in hass.data[DOMAIN].items():
                if not isinstance(entry_data, dict) or "api_client" not in entry_data:
                    continue
                entry_sn = None
                for cfg_entry in hass.config_entries.async_entries(DOMAIN):
                    if cfg_entry.entry_id == eid:
                        entry_sn = cfg_entry.data.get(CONF_DEVICE_SN)
                        break
                if entry_sn == sn or api is None:
                    api = entry_data["api_client"]
                    web = entry_data.get("web_client")
                    resolved_sn = entry_sn or sn
                if entry_sn == sn:
                    break
            if api is None:
                raise ValueError(f"No foxess_ws entry found for device_sn={sn}")
            return api, web, resolved_sn

        async def _set_scheduler_via_web_or_fail(
            web: FoxESSWebClient | None,
            groups: list[dict],
        ) -> None:
            """Write scheduler via web API. Raises if unavailable or fails."""
            if web is None:
                raise RuntimeError(
                    "Web API client not available (deviceID resolution failed at startup)"
                )
            await web.set_scheduler(groups)

        async def _notify(title: str, message: str) -> None:
            """Create a persistent notification."""
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {"title": title, "message": message},
            )

        async def async_handle_set_scheduler(call: ServiceCall) -> None:
            """Handle foxess_ws.set_scheduler service call."""
            sn = call.data.get("device_sn", device_sn)
            groups = call.data["groups"]
            api, web, resolved_sn = _resolve_clients(sn)
            try:
                await _set_scheduler_via_web_or_fail(web, groups)
            except Exception as exc:
                _LOGGER.error("set_scheduler failed on %s: %s", resolved_sn, exc)
                modes = [g.get("workMode", "?") for g in groups]
                await _notify(
                    "FoxESS Scheduler FAILED",
                    f"Could not update {resolved_sn}.\nGroups: {', '.join(modes)}\nError: {exc}",
                )
                raise
            modes = [g.get("workMode", "?") for g in groups]
            _LOGGER.info(
                "set_scheduler service: updated %s with %d groups",
                resolved_sn,
                len(groups),
            )
            await _notify(
                "FoxESS Scheduler Updated",
                f"Wrote {len(groups)} groups to {resolved_sn}: {', '.join(modes)}",
            )

        hass.services.async_register(
            DOMAIN,
            "set_scheduler",
            async_handle_set_scheduler,
            schema=vol.Schema(
                {
                    vol.Optional("device_sn"): cv.string,
                    vol.Required("groups"): vol.Any(list, dict),
                }
            ),
        )

    _LOGGER.info("FoxESS WebSocket integration started for %s", device_sn)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a FoxESS WebSocket config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        coordinator: FoxESSWSCoordinator = data["coordinator"]
        await coordinator.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Remove domain services if no entries remain
    remaining = [
        eid
        for eid in hass.data.get(DOMAIN, {})
        if isinstance(hass.data[DOMAIN].get(eid), dict) and "api_client" in hass.data[DOMAIN][eid]
    ]
    if not remaining:
        if hass.services.has_service(DOMAIN, "set_scheduler"):
            hass.services.async_remove(DOMAIN, "set_scheduler")

    return unload_ok
