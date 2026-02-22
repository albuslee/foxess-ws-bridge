"""Constants for the FoxESS WebSocket integration."""

from pathlib import Path

DOMAIN = "foxess_ws"

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_API_KEY = "api_key"
CONF_DEVICE_SN = "device_sn"
CONF_PLANT_ID = "plant_id"
CONF_PLANT_NAME = "plant_name"
CONF_DEVICE_NAME = "device_name"

# FoxESS Web API (for WebSocket auth)
FOXESS_BASE_URL = "https://www.foxesscloud.com"
FOXESS_LOGIN_URL = "/basic/v0/user/login"
FOXESS_PLANT_LIST_URL = "/dew/v0/plant/droplistForWeb"
FOXESS_LOGOUT_URL = "/basic/v0/user/logout"

# FoxESS WebSocket
FOXESS_WS_URL = "wss://www.foxesscloud.com/dew/v0/wsmaitian"
WS_KEEPALIVE_INTERVAL = 30  # seconds
WS_RECONNECT_CYCLE = 480  # seconds — reconnect before server throttles pushes
WS_RECONNECT_MIN = 1  # seconds
WS_RECONNECT_MAX = 60  # seconds

# FoxESS Web API (for fast writes via browser-style auth)
WEBAPI_PLANT_DEVICES = "/dew/v0/plant/devices"
WEBAPI_SCHEDULER_SET = "/dew/v2/device/scheduler/set"
WEBAPI_SCHEDULER_GET = "/dew/v3/device/scheduler/get"

# FoxESS OpenAPI (for writes/control — fallback)
FOXESS_OPENAPI_BASE = "https://www.foxesscloud.com"
OPENAPI_DEVICE_LIST = "/op/v0/device/list"
OPENAPI_SETTING_SET = "/op/v0/device/setting/set"
OPENAPI_SETTING_GET = "/op/v0/device/setting/get"
OPENAPI_SCHEDULER_ENABLE = "/op/v3/device/scheduler/enable"
OPENAPI_SCHEDULER_GET = "/op/v3/device/scheduler/get"
OPENAPI_SCHEDULER_FLAG_GET = "/op/v0/device/scheduler/get/flag"
OPENAPI_SCHEDULER_FLAG_SET = "/op/v1/device/scheduler/set/flag"

# Token expiry error codes
TOKEN_EXPIRED_CODES = {41808, 41809, 41810}

# WASM
WASM_PATH = Path(__file__).parent / "wasm" / "signature.wasm"

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "select", "number", "switch", "button"]

# Battery charge states
BATTERY_CHARGE_IDLE = 0
BATTERY_CHARGE_CHARGING = 1
BATTERY_CHARGE_DISCHARGING = 2

BATTERY_CHARGE_MAP = {
    0: "idle",
    1: "charging",
    2: "discharging",
}

# Work modes
WORK_MODES = ["SelfUse", "Feedin", "Backup", "PeakShaving"]
SCHEDULER_WORK_MODES = [
    "SelfUse",
    "Feedin",
    "Backup",
    "ForceCharge",
    "ForceDischarge",
]
