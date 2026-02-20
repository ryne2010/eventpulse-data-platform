"""Generate contract-compliant sample files.

Outputs files under ./data/samples by default.

Files:
- parcels_baseline.xlsx (valid)
- parcels_drift_add_column.xlsx (extra column)
- parcels_drift_type_change.xlsx (sale_price coerced to string)
- parcels_quality_fail_duplicate_pk.xlsx (duplicate parcel_id)

Usage:
  python scripts/generate_sample_data.py --rows 100 --out-dir data/samples
"""

from __future__ import annotations

import argparse
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def build_parcels(rows: int, *, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)

    base_date = datetime(2024, 1, 1)
    out = []

    for i in range(rows):
        parcel_id = f"P{100000 + i}"
        county = random.choice(["Springfield", "Shelby", "Ogdenville"])
        city = random.choice(["Springfield", "Shelbyville", "Ogdenville"])
        state = "CO"
        zip_code = str(random.choice(["81073", "81074", "81075"]))
        lat = 39.0 + random.random() * 0.5
        lon = -104.0 - random.random() * 0.5
        sale_date = base_date + timedelta(days=random.randint(0, 365))
        recording_date = sale_date + timedelta(days=random.randint(0, 30))
        sale_price = round(random.uniform(150_000, 850_000), 2)
        deed_type = random.choice(["Warranty", "Quitclaim", None])
        doc_number = f"DOC{random.randint(100000, 999999)}" if random.random() > 0.2 else None
        book = str(random.randint(1, 999)) if random.random() > 0.4 else None
        page = str(random.randint(1, 500)) if random.random() > 0.4 else None
        grantor = random.choice(["Smith", "Johnson", "Williams", None])
        grantee = random.choice(["Brown", "Jones", "Miller", None])
        year_built = random.choice([1985, 1992, 2001, 2010, None])
        bedrooms = random.choice([2, 3, 4, 5, None])
        bathrooms = random.choice([1.0, 1.5, 2.0, 2.5, 3.0, None])
        building_sqft = random.choice([1200, 1500, 1800, 2200, 2800, None])
        lot_sqft = random.choice([4000, 6000, 8000, 12000, None])
        assessed_value = round(sale_price * random.uniform(0.8, 1.2), 2) if random.random() > 0.3 else None
        land_use = random.choice(["Residential", "Commercial", "Agricultural", None])
        updated_at = recording_date + timedelta(hours=random.randint(0, 72))

        out.append(
            {
                "parcel_id": parcel_id,
                "county": county,
                "situs_address": f"{random.randint(100, 9999)} Main St" if random.random() > 0.05 else None,
                "city": city,
                "state": state,
                "zip": zip_code,
                "lat": lat,
                "lon": lon,
                "sale_date": sale_date,
                "recording_date": recording_date,
                "sale_price": sale_price,
                "deed_type": deed_type,
                "doc_number": doc_number,
                "book": book,
                "page": page,
                "grantor": grantor,
                "grantee": grantee,
                "year_built": year_built,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "building_sqft": building_sqft,
                "lot_sqft": lot_sqft,
                "assessed_value": assessed_value,
                "land_use": land_use,
                "updated_at": updated_at,
            }
        )

    return pd.DataFrame(out)


def build_edge_telemetry(rows: int, *, seed: int = 31415, device_count: int = 4) -> pd.DataFrame:
    """Generate synthetic edge telemetry events.

    Output is CSV-friendly and aligned with data/contracts/edge_telemetry.yaml.
    """

    rng = random.Random(seed)
    base_dt = datetime(2025, 1, 1, 0, 0, 0)

    sensors = [
        ("temp_c", "C", 5.0, 45.0),
        ("humidity_pct", "%", 5.0, 95.0),
        ("water_pressure_psi", "psi", 0.0, 120.0),
        ("oil_pressure_psi", "psi", 0.0, 100.0),
        ("oil_life_pct", "%", 0.0, 100.0),
        ("oil_level_pct", "%", 0.0, 100.0),
        ("drip_oil_level_pct", "%", 0.0, 100.0),
        ("vibration_g", "g", 0.0, 1.5),
    ]

    out = []
    ns = uuid.UUID("9a1d7d3a-0e2e-4e93-84b8-0e7f2f8d3c0a")
    for i in range(rows):
        device_id = f"rpi-{(i % device_count) + 1:02d}"
        ts = base_dt + timedelta(seconds=i * 30 + rng.randint(0, 5))

        is_hb = rng.random() < 0.2
        event_type = "heartbeat" if is_hb else "reading"

        if is_hb:
            sensor = None
            value = None
            units = None
            status = rng.choice(["ok", "ok", "ok", "degraded"])  # mostly OK
            message = None
        else:
            sensor, units, lo, hi = rng.choice(sensors)
            value = round(rng.uniform(lo, hi), 3)
            status = None
            message = None

        lat = 39.0 + rng.random() * 0.25
        lon = -104.0 - rng.random() * 0.25

        battery_v = round(rng.uniform(3.6, 4.2), 3)
        rssi_dbm = int(rng.uniform(-112, -70))
        fw = rng.choice(["edge-agent/0.2.0", "edge-agent/0.3.5"])

        # Deterministic event_id for repeatable sample files.
        event_id = str(uuid.uuid5(ns, f"{device_id}:{ts.isoformat()}:{sensor}:{value}"))

        out.append(
            {
                "event_id": event_id,
                "device_id": device_id,
                "event_type": event_type,
                "sensor": sensor,
                "value": value,
                "units": units,
                "ts": ts.isoformat(),
                "lat": lat,
                "lon": lon,
                "battery_v": battery_v,
                "rssi_dbm": rssi_dbm,
                "firmware_version": fw,
                "status": status,
                "message": message,
            }
        )

    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=60)
    ap.add_argument("--out-dir", type=str, default="data/samples")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = build_parcels(args.rows)
    baseline_path = out_dir / "parcels_baseline.xlsx"
    baseline.to_excel(baseline_path, index=False)

    drift_add = baseline.copy()
    drift_add["zoning"] = [random.choice(["A", "R1", "R2", "C1", "M"]) for _ in range(len(drift_add))]
    drift_add_path = out_dir / "parcels_drift_add_column.xlsx"
    drift_add.to_excel(drift_add_path, index=False)

    drift_type = baseline.copy()
    drift_type["sale_price"] = drift_type["sale_price"].astype(str)
    drift_type_path = out_dir / "parcels_drift_type_change.xlsx"
    drift_type.to_excel(drift_type_path, index=False)

    qfail = baseline.copy()
    if len(qfail) >= 2:
        qfail.loc[0, "parcel_id"] = qfail.loc[1, "parcel_id"]
    qfail_path = out_dir / "parcels_quality_fail_duplicate_pk.xlsx"
    qfail.to_excel(qfail_path, index=False)

    # ---------------------------------------------------------------------
    # Edge telemetry samples (CSV)
    # ---------------------------------------------------------------------

    edge_base = build_edge_telemetry(args.rows)
    edge_base_path = out_dir / "edge_telemetry_sample.csv"
    edge_base.to_csv(edge_base_path, index=False)

    edge_drift_add = edge_base.copy()
    edge_drift_add["carrier"] = [random.choice(["verizon", "att", "tmobile"]) for _ in range(len(edge_drift_add))]
    edge_drift_add_path = out_dir / "edge_telemetry_drift_add_column.csv"
    edge_drift_add.to_csv(edge_drift_add_path, index=False)

    edge_drift_type = edge_base.copy()
    edge_drift_type["rssi_dbm"] = edge_drift_type["rssi_dbm"].astype(str)
    edge_drift_type_path = out_dir / "edge_telemetry_drift_type_change.csv"
    edge_drift_type.to_csv(edge_drift_type_path, index=False)

    edge_qfail = edge_base.copy()
    if len(edge_qfail) >= 2:
        edge_qfail.loc[0, "event_id"] = edge_qfail.loc[1, "event_id"]
    edge_qfail_path = out_dir / "edge_telemetry_quality_fail_duplicate_pk.csv"
    edge_qfail.to_csv(edge_qfail_path, index=False)

    print("Wrote:")
    for p in [
        baseline_path,
        drift_add_path,
        drift_type_path,
        qfail_path,
        edge_base_path,
        edge_drift_add_path,
        edge_drift_type_path,
        edge_qfail_path,
    ]:
        print(" -", p)


if __name__ == "__main__":
    main()
