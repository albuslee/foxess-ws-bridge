# FoxESS WebSocket Bridge

[![HACS Validation](https://github.com/albuslee/foxess-ws-bridge/actions/workflows/validate.yml/badge.svg)](https://github.com/albuslee/foxess-ws-bridge/actions/workflows/validate.yml)
[![Lint](https://github.com/albuslee/foxess-ws-bridge/actions/workflows/lint.yml/badge.svg)](https://github.com/albuslee/foxess-ws-bridge/actions/workflows/lint.yml)

A custom [Home Assistant](https://www.home-assistant.io/) integration that provides **real-time (~5 second) solar inverter monitoring** via the FoxESS Cloud WebSocket API, plus full scheduler control via the fast web API.

## Why This Integration?

The official FoxESS OpenAPI only supports polling at 5-minute intervals. This integration connects to the same WebSocket endpoint used by the foxesscloud.com web dashboard, providing push-based updates every ~5 seconds. This enables:

- Real-time power flow dashboards
- Fast-reacting automations (e.g., dynamic discharge power based on house load)
- Accurate energy tracking without 5-minute gaps

## Features

- **Real-time data via WebSocket** — ~5 second push updates (no polling)
- **Power sensors** — Solar, grid, battery, load, backup load, aux power
- **Battery state** — SoC percentage, charge/discharge/idle state
- **Grid status** — Importing, exporting, or idle
- **Work mode control** — SelfUse, Feedin, Backup, PeakShaving
- **Scheduler control** — Full read/write of charge/discharge schedules via fast web API
- **Min SoC & Export Limit** — Number entities for key inverter settings
- **Scheduler switch** — Enable/disable the charge scheduler
- **Auto-reconnection** — Exponential backoff with forced reconnect every 8 minutes to maintain push frequency

## Prerequisites

- A FoxESS inverter registered on [foxesscloud.com](https://www.foxesscloud.com)
- FoxESS Cloud account credentials (email + password)
- FoxESS OpenAPI key (from Profile > API Management on foxesscloud.com)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu > Custom repositories
3. Add `https://github.com/albuslee/foxess-ws-bridge` with category **Integration**
4. Search for "FoxESS WebSocket" and install
5. Restart Home Assistant
6. Go to Settings > Integrations > Add Integration > **FoxESS WebSocket**

### Manual

1. Copy the `custom_components/foxess_ws` folder to your Home Assistant `custom_components/` directory
2. Restart Home Assistant
3. Add via Settings > Integrations > Add Integration > **FoxESS WebSocket**

## Configuration

The integration uses a UI config flow:

1. **Credentials** — Enter your FoxESS Cloud email, password, and OpenAPI key
2. **Device Selection** — Choose your inverter from the auto-discovered list

The timezone is automatically derived from your Home Assistant system configuration.

## Entities

### Sensors

| Entity | Description | Unit |
|--------|-------------|------|
| Solar Power | Current PV generation | W |
| Grid Power | Grid import (+) / export (-) | W |
| Battery Power | Charge (+) / discharge (-) | W |
| Battery SoC | State of charge | % |
| Load Power | Total household consumption | W |
| Normal Load | Non-backup circuit load | W |
| Backup Load | Backup circuit load | W |
| Aux Power | Auxiliary power | W |
| Battery Charge State | idle / charging / discharging | — |
| Grid Status | importing / exporting / idle | — |
| Time Flag | day / night | — |

### Controls

| Entity | Type | Description |
|--------|------|-------------|
| Work Mode | Select | SelfUse, Feedin, Backup, PeakShaving |
| Min SoC (On Grid) | Number | Minimum battery SoC (0-100%) |
| Export Limit | Number | Grid export limit (W) |
| Scheduler | Switch | Enable/disable charge scheduler |

### Buttons

| Entity | Description |
|--------|-------------|
| Refresh | Force WebSocket + API data refresh |
| Read Settings | Read and log all current inverter settings |
| Test Scheduler Write | Round-trip scheduler read/write verification |

### Binary Sensors

| Entity | Description |
|--------|-------------|
| WebSocket Connected | Connection health indicator |

## Services

### `foxess_ws.set_scheduler`

Write a complete charge/discharge schedule to the inverter (full overwrite).

```yaml
service: foxess_ws.set_scheduler
data:
  groups:
    - startHour: 0
      startMinute: 0
      endHour: 5
      endMinute: 59
      workMode: ForceCharge
      extraParam:
        fdSoc: 100
        fdPwr: 10500
        minSocOnGrid: 10
        maxSoc: 100
    - startHour: 6
      startMinute: 0
      endHour: 23
      endMinute: 59
      workMode: SelfUse
      extraParam:
        fdSoc: 10
        fdPwr: 6500
        minSocOnGrid: 10
        maxSoc: 100
```

**Fields:**
- `groups` (required) — List of scheduler group objects
- `device_sn` (optional) — Target inverter SN (defaults to configured device)

**Each group must include:**
- `startHour`, `startMinute`, `endHour`, `endMinute` — Time window
- `workMode` — One of: `SelfUse`, `Feedin`, `Backup`, `ForceCharge`, `ForceDischarge`
- `extraParam` — Object with `fdSoc`, `fdPwr`, `minSocOnGrid`, `maxSoc`

## Example Automations

### Charge from solar during midday, discharge during evening peak

```yaml
automation:
  - alias: "Daily charge/discharge schedule"
    trigger:
      - platform: time
        at: "05:00:00"
    action:
      - service: foxess_ws.set_scheduler
        data:
          groups:
            - startHour: 11
              startMinute: 0
              endHour: 13
              endMinute: 59
              workMode: ForceCharge
              extraParam:
                fdSoc: 100
                fdPwr: 10500
                minSocOnGrid: 10
                maxSoc: 100
            - startHour: 18
              startMinute: 0
              endHour: 19
              endMinute: 59
              workMode: ForceDischarge
              extraParam:
                fdSoc: 10
                fdPwr: 6500
                minSocOnGrid: 10
                maxSoc: 100
            - startHour: 0
              startMinute: 0
              endHour: 23
              endMinute: 59
              workMode: SelfUse
              extraParam:
                fdSoc: 10
                fdPwr: 6500
                minSocOnGrid: 10
                maxSoc: 100
```

### Adaptive discharge plan based on battery SoC

```yaml
script:
  adaptive_discharge:
    alias: "Adaptive Discharge Plan"
    sequence:
      - choose:
          # High SoC: discharge early + peak + late
          - conditions:
              - condition: numeric_state
                entity_id: sensor.foxess_battery_soc
                above: 80
            sequence:
              - service: foxess_ws.set_scheduler
                data:
                  groups:
                    - startHour: 11
                      startMinute: 0
                      endHour: 13
                      endMinute: 59
                      workMode: ForceCharge
                      extraParam: { fdSoc: 100, fdPwr: 10500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 17
                      startMinute: 30
                      endHour: 17
                      endMinute: 59
                      workMode: ForceDischarge
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 18
                      startMinute: 0
                      endHour: 19
                      endMinute: 59
                      workMode: ForceDischarge
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 20
                      startMinute: 0
                      endHour: 20
                      endMinute: 59
                      workMode: ForceDischarge
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 0
                      startMinute: 0
                      endHour: 23
                      endMinute: 59
                      workMode: SelfUse
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
          # Medium SoC: peak only
          - conditions:
              - condition: numeric_state
                entity_id: sensor.foxess_battery_soc
                above: 50
            sequence:
              - service: foxess_ws.set_scheduler
                data:
                  groups:
                    - startHour: 11
                      startMinute: 0
                      endHour: 13
                      endMinute: 59
                      workMode: ForceCharge
                      extraParam: { fdSoc: 100, fdPwr: 10500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 18
                      startMinute: 0
                      endHour: 19
                      endMinute: 59
                      workMode: ForceDischarge
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
                    - startHour: 0
                      startMinute: 0
                      endHour: 23
                      endMinute: 59
                      workMode: SelfUse
                      extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
        # Low SoC: self-use only (no discharge)
        default:
          - service: foxess_ws.set_scheduler
            data:
              groups:
                - startHour: 11
                  startMinute: 0
                  endHour: 13
                  endMinute: 59
                  workMode: ForceCharge
                  extraParam: { fdSoc: 100, fdPwr: 10500, minSocOnGrid: 10, maxSoc: 100 }
                - startHour: 0
                  startMinute: 0
                  endHour: 23
                  endMinute: 59
                  workMode: SelfUse
                  extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
```

### Dynamic discharge power based on house load

```yaml
automation:
  - alias: "Adjust discharge power during peak"
    trigger:
      - platform: numeric_state
        entity_id: sensor.foxess_load_power
        above: 1500
    condition:
      - condition: time
        after: "18:00:00"
        before: "20:00:00"
    action:
      - service: foxess_ws.set_scheduler
        data:
          groups:
            - startHour: 18
              startMinute: 0
              endHour: 19
              endMinute: 59
              workMode: ForceDischarge
              extraParam:
                fdSoc: 10
                fdPwr: >-
                  {{ (states('sensor.foxess_load_power') | int + 5000) | min(10500) }}
                minSocOnGrid: 10
                maxSoc: 100
            - startHour: 0
              startMinute: 0
              endHour: 23
              endMinute: 59
              workMode: SelfUse
              extraParam: { fdSoc: 10, fdPwr: 6500, minSocOnGrid: 10, maxSoc: 100 }
```

## How It Works

### WebSocket Connection

The integration connects to `wss://www.foxesscloud.com/dew/v0/wsmaitian` — the same endpoint used by the FoxESS web dashboard. This provides push-based data every ~5 seconds.

To maintain the fast push frequency, the connection is deliberately closed and reopened every 480 seconds (the server throttles long-lived connections).

### WASM Signature

The FoxESS web portal requires a cryptographic `signature` header on every request. The algorithm is compiled into a WebAssembly module (`signature.wasm`) that the portal's JavaScript calls at runtime.

Rather than reverse-engineering the obfuscated algorithm, this integration runs the same WASM binary using [wasmtime](https://wasmtime.dev/) (a lightweight, sandboxed WebAssembly runtime). This provides exact compatibility with the browser and zero maintenance burden when FoxESS updates their portal.

The `signature.wasm` file originates from the FoxESS web portal and is their intellectual property. It is included here solely for interoperability purposes.

### Dual API Approach

| API | Auth | Use Case | Speed |
|-----|------|----------|-------|
| Web API | WASM signature | Scheduler writes | Fast, no rate limit |
| OpenAPI | API key + MD5 | Settings control (work mode, min SoC, export limit) | Rate limited |

The web API is preferred for scheduler operations because it responds immediately and has no rate limiting. The OpenAPI is used for device settings and as a fallback.

## Related Projects

- [nicois/foxess-control](https://github.com/nicois/foxess-control) — Similar WASM+WebSocket approach with smart battery algorithms
- [macxq/foxess-ha](https://github.com/macxq/foxess-ha) — FoxESS OpenAPI polling integration
- [nickw444/ha-foxess-cloud](https://github.com/nickw444/ha-foxess-cloud) — FoxESS OpenAPI with scheduler support

## License

[MIT](LICENSE)
