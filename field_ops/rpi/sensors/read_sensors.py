#!/usr/bin/env python3
"""Minimal sensor script for EventPulse edge agent (script mode).

This script is intentionally dependency-free so you can iterate quickly on a Raspberry Pi.
It prints a JSON array of readings to stdout.

To use on a Pi:
  1) Copy this file into the spool volume (mounted into the container):
       sudo cp field_ops/rpi/sensors/read_sensors.py /var/lib/eventpulse-edge/spool/read_sensors.py
       sudo chmod +x /var/lib/eventpulse-edge/spool/read_sensors.py
  2) Set in /etc/eventpulse-edge/edge.env:
       EDGE_SENSOR_MODE=script
       EDGE_SENSOR_SCRIPT="python3 /data/spool/read_sensors.py"

The edge agent accepts JSON objects, JSON arrays, CSV lines, or a single float.
See services/edge_agent/README.md for details.

Extend this script with real hardware drivers as needed.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> int:
    # If you want deterministic output for demos, set EDGE_SEED.
    seed_raw = os.environ.get("EDGE_SEED", "")
    rng = random.Random(int(seed_raw)) if seed_raw.strip().isdigit() else random.Random()

    # You can switch to real hardware drivers by setting USE_HARDWARE=1 and adding deps.
    use_hardware = _truthy(os.environ.get("USE_HARDWARE", "false"))

    # NOTE: This script does not emit ts/device_id; the edge agent enriches + timestamps.
    if use_hardware:
        # Placeholder: read real sensors here.
        # Keep the output schema the same: [{"sensor":..., "value":..., "units":...}, ...]
        # Example: BME280 over I2C + ADS1115 for analog pressures.
        pass

    readings = [
        {"sensor": "temp_c", "value": round(rng.uniform(5.0, 45.0), 2), "units": "C"},
        {"sensor": "humidity_pct", "value": round(rng.uniform(5.0, 95.0), 1), "units": "%"},
        {"sensor": "water_pressure_psi", "value": round(rng.uniform(0.0, 120.0), 1), "units": "psi"},
        {"sensor": "oil_pressure_psi", "value": round(rng.uniform(0.0, 100.0), 1), "units": "psi"},
        {"sensor": "oil_life_pct", "value": round(rng.uniform(0.0, 100.0), 0), "units": "%"},
        {"sensor": "oil_level_pct", "value": round(rng.uniform(0.0, 100.0), 0), "units": "%"},
        {"sensor": "drip_oil_level_pct", "value": round(rng.uniform(0.0, 100.0), 0), "units": "%"},
    ]

    # For a script, stdout must be the only output (avoid prints to stderr).
    sys.stdout.write(json.dumps(readings))
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Optional: throttle in case you run this standalone.
    if _truthy(os.environ.get("SENSOR_SCRIPT_SLEEP", "false")):
        time.sleep(0.2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
