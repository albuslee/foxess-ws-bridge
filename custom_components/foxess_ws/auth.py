"""FoxESS Web Authentication — WASM signature + login for WebSocket access."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

import ctypes

import aiohttp
from wasmtime import Engine, FuncType, Linker, Memory, Module, Store, ValType

from .const import (
    FOXESS_BASE_URL,
    FOXESS_LOGIN_URL,
    FOXESS_LOGOUT_URL,
    FOXESS_PLANT_LIST_URL,
    WASM_PATH,
)

_LOGGER = logging.getLogger(__name__)


def load_wasm(wasm_path: str | None = None) -> Callable[..., str]:
    """Load the FoxESS signature WASM module.

    Returns a callable: get_signature(url, token, lang, timestamp) -> str
    """
    path = wasm_path or str(WASM_PATH)
    engine = Engine()
    module = Module.from_file(engine, path)
    linker = Linker(engine)
    store = Store(engine)

    # Emscripten stubs required by the WASM module
    memory_ref: list[Memory] = []

    def _emscripten_memcpy_big(_caller: object, dest: int, src: int, num: int) -> int:
        mem = memory_ref[0]
        base = ctypes.cast(mem.data_ptr(store), ctypes.c_void_p).value
        ctypes.memmove(base + dest, base + src, num)
        return dest

    def _emscripten_resize_heap(_size: int) -> int:
        return 0

    def _set_temp_ret0(_val: int) -> None:
        pass

    i32 = ValType.i32()
    linker.define_func(
        "env", "emscripten_memcpy_big",
        FuncType([i32, i32, i32], [i32]),
        _emscripten_memcpy_big, access_caller=True,
    )
    linker.define_func(
        "env", "emscripten_resize_heap",
        FuncType([i32], [i32]),
        _emscripten_resize_heap,
    )
    linker.define_func(
        "env", "setTempRet0",
        FuncType([i32], []),
        _set_temp_ret0,
    )

    instance = linker.instantiate(store, module)
    exports = instance.exports(store)

    memory = exports["memory"]
    if memory is None:
        raise RuntimeError("WASM module does not export 'memory'")
    memory_ref.append(memory)

    begin_signature = exports["begin_signature"]
    end_signature = exports["end_signature"]
    stack_alloc = exports["stackAlloc"]
    stack_save = exports["stackSave"]
    stack_restore = exports["stackRestore"]

    def _write_string(s: str) -> int:
        """Write a null-terminated UTF-8 string into WASM memory, return pointer."""
        encoded = s.encode("utf-8") + b"\x00"
        ptr = stack_alloc(store, len(encoded))
        base = ctypes.cast(memory.data_ptr(store), ctypes.c_void_p).value
        ctypes.memmove(base + ptr, encoded, len(encoded))
        return ptr

    def _read_string(ptr: int) -> str:
        """Read a null-terminated UTF-8 string from WASM memory."""
        base = ctypes.cast(memory.data_ptr(store), ctypes.c_void_p).value
        result = b""
        offset = 0
        while True:
            byte = ctypes.c_ubyte.from_address(base + ptr + offset).value
            if byte == 0:
                break
            result += bytes([byte])
            offset += 1
        return result.decode("utf-8")

    def get_signature(url: str, token: str, lang: str, timestamp: str) -> str:
        """Generate a FoxESS API signature using the WASM module."""
        sp = stack_save(store)
        try:
            url_ptr = _write_string(url)
            token_ptr = _write_string(token)
            lang_ptr = _write_string(lang)
            ts_ptr = _write_string(timestamp)

            result_ptr = begin_signature(store, url_ptr, token_ptr, lang_ptr, ts_ptr)
            signature = _read_string(result_ptr)
            end_signature(store, result_ptr)
            return signature
        finally:
            stack_restore(store, sp)

    return get_signature


def _build_headers(
    url_path: str,
    token: str,
    get_signature: Callable[..., str],
    tz: str = "Australia/Sydney",
) -> dict[str, str]:
    """Build request headers with WASM signature for the FoxESS web API."""
    ts = str(int(time.time() * 1000))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    dt_val = f"{tz}@{ts}@{now}"
    signature = get_signature(url_path, token, "en", ts)

    return {
        "Content-Type": "application/json",
        "lang": "en",
        "token": token,
        "timezone": tz,
        "platform": "web",
        "timestamp": ts,
        "dt": dt_val,
        "signature": signature,
    }


async def logout(
    session: aiohttp.ClientSession,
    get_signature: Callable[..., str],
    token: str,
) -> None:
    """Logout from FoxESS Cloud to destroy the current session."""
    headers = _build_headers(FOXESS_LOGOUT_URL, token, get_signature)
    url = f"{FOXESS_BASE_URL}{FOXESS_LOGOUT_URL}"
    try:
        async with session.post(url, json={}, headers=headers) as resp:
            data: dict[str, Any] = await resp.json()
        if data.get("errno") != 0:
            _LOGGER.warning("Logout returned errno=%s", data.get("errno"))
        else:
            _LOGGER.debug("Logout successful")
    except Exception:
        _LOGGER.warning("Logout request failed", exc_info=True)


async def login(
    session: aiohttp.ClientSession,
    get_signature: Callable[..., str],
    email: str,
    password: str,
) -> str:
    """Login to FoxESS Cloud and return a session token."""
    md5_pass = hashlib.md5(password.encode()).hexdigest()
    headers = _build_headers(FOXESS_LOGIN_URL, "", get_signature)
    payload = {
        "user": email,
        "password": md5_pass,
        "type": 1,
        "verification": 1,
    }

    url = f"{FOXESS_BASE_URL}{FOXESS_LOGIN_URL}"
    async with session.post(url, json=payload, headers=headers) as resp:
        data: dict[str, Any] = await resp.json()

    if data.get("errno") != 0:
        raise AuthenticationError(
            f"Login failed: errno={data.get('errno')}, msg={data.get('msg')}"
        )

    token = data["result"]["token"]
    _LOGGER.debug("Login successful, token obtained")
    return token


async def get_plants(
    session: aiohttp.ClientSession,
    get_signature: Callable[..., str],
    token: str,
) -> list[dict[str, Any]]:
    """Fetch the list of plants for the logged-in user."""
    url_path = f"{FOXESS_PLANT_LIST_URL}?plantName="
    headers = _build_headers(url_path, token, get_signature)

    url = f"{FOXESS_BASE_URL}{url_path}"
    async with session.get(url, headers=headers) as resp:
        data: dict[str, Any] = await resp.json()

    if data.get("errno") != 0:
        raise AuthenticationError(
            f"Failed to fetch plants: errno={data.get('errno')}, msg={data.get('msg')}"
        )

    return data.get("result", [])


def build_ws_url(plant_id: str, token: str) -> str:
    """Build the WebSocket connection URL."""
    from .const import FOXESS_WS_URL

    encoded_token = quote(token, safe="")
    return f"{FOXESS_WS_URL}?plantId={plant_id}&token={encoded_token}&platform=web&lang=en"


class AuthenticationError(Exception):
    """Raised when FoxESS authentication fails."""
