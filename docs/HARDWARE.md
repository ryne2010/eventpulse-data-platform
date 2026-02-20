# Field hardware (cheap + available)

This repo is designed to run on inexpensive, widely available field hardware.

The main constraints:

- must run Linux reliably (headless)
- must tolerate intermittent connectivity (LTE/5G)
- must survive reboots/power loss without corrupting state
- must run a small Docker container (the edge agent)

## Recommended baseline

### Budget field kit (pragmatic defaults)

- Raspberry Pi 4B (4GB)
- Rugged case + active cooling (fan)
- High-endurance microSD *or* small USB SSD
- Official-ish power supply + short cable
- External LTE/5G router with Ethernet (simplifies drivers)
- Optional: inline UPS / battery pack if brownouts are common

### Compute

- **Raspberry Pi 4 Model B (2GB or 4GB)**
  - Most mature ecosystem + accessories
  - Plenty of headroom for one or two lightweight containers

Alternative:

- **Raspberry Pi 5 (4GB)** if you need more CPU (more expensive and higher power draw)

### Storage

Avoid cheap microSD cards for field deployments.

Recommended:

- **High-endurance microSD** (32–128GB) *or*
- **USB 3 SSD** (preferred for reliability)

EventPulse stores its local state here:

- `/var/lib/eventpulse-edge/spool/` (telemetry spool + the device token file)

### Power

- Official Raspberry Pi USB-C (Pi 5) or USB-C/USB micro (Pi 4) power supply
- Optional: inline **UPS / battery HAT** if you expect frequent brownouts

## Connectivity options (ordered by ease)

### Option A: External cellular router (easiest)

Use a dedicated LTE/5G router that accepts a SIM and provides Wi‑Fi/Ethernet.

Pros:

- easiest to deploy and troubleshoot
- fewer Linux modem driver surprises
- often more stable in fringe coverage

Cons:

- typically more expensive than modem HATs

### Option B: 4G LTE modem/HAT (cheapest)

A 4G LTE modem HAT (e.g., SIM7600-based) is usually the lowest-cost setup.

Pros:

- inexpensive
- widely available

Cons:

- not true 5G, but most “5G data SIMs” still work on LTE

### Option C: 5G modem kit/HAT (true 5G)

A 5G modem kit (often using an M.2 modem such as RM520N‑GL) gives true 5G where available.

Pros:

- true 5G

Cons:

- higher cost
- more configuration complexity

## Sensor interface

This reference implementation doesn’t prescribe your sensor stack.

Common sensor patterns:

- USB serial sensors
- I2C/SPI sensors (requires enabling interfaces)
- A separate microcontroller (ESP32/Arduino) feeding the Pi over serial

The edge agent supports these sensor modes:

- `EDGE_SENSOR_MODE=simulated` — demo mode
- `EDGE_SENSOR_MODE=stdin` — pipe lightweight readings into the agent (JSON, CSV, or float)
- `EDGE_SENSOR_MODE=script` — run a script that prints readings (JSON, CSV, or float)



## Sensor recommendations for this project

You asked for: **temperature**, **humidity**, **water pressure**, **oil pressure**, **oil life %**, **oil level**, and **drip oil level**.
Below is a cheap + available baseline that maps cleanly to the `edge_telemetry` contract.

### Core sensing (low cost, easy to source)

- **Temp + humidity:** BME280 (I2C) or SHT31 (I2C)
  - BME280 boards are extremely common and inexpensive.
- **Analog channels (pressure + level):** ADS1115 (I2C, 16‑bit ADC)
  - Raspberry Pi has **no native analog input**, so an ADC breakout is the simplest path.
- **Water pressure:** 0–100 PSI transducer with **0.5–4.5V** output (automotive‑style)
- **Oil pressure:** 0–100 PSI transducer with **0.5–4.5V** output
- **Oil level + drip oil level:**
  - Cheapest: **float switch** (digital) in a reservoir/drip pan
  - More continuous readings: **ultrasonic distance sensor** aimed at the surface, or an analog level sensor via ADS1115

### “Oil life %” in practice

Oil life is usually a **derived metric** (hours of operation, temperature history, load, time since last service).
For a field MVP, treat it as either:

- a value computed on-device (simple heuristic), or
- a value set by an operator / maintenance workflow

### Camera

- **Snapshot / video:** USB UVC webcam (cheapest, universal) *or* Raspberry Pi Camera Module (better integration)
- For an MVP, a periodic **snapshot** is often enough (video adds bandwidth + storage complexity on cellular).

### Mapping to EventPulse telemetry

Recommended sensor names + units (matches UI expectations):

- `temp_c` (C)
- `humidity_pct` (%)
- `water_pressure_psi` (psi)
- `oil_pressure_psi` (psi)
- `oil_life_pct` (%)
- `oil_level_pct` (%)
- `drip_oil_level_pct` (%)

You can implement these using the edge agent’s `script` mode (see `services/edge_agent/README.md` for formats).


See `docs/FIELD_OPS.md` for a full walkthrough.
