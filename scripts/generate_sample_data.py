#!/usr/bin/env python3
"""Generate synthetic 'assessor-style' files for demo ingestion.

Creates:
- parcels_baseline.xlsx
- parcels_drift_add_column.xlsx (adds a new column to demonstrate drift)
- parcels_bad_quality.xlsx (violates quality gates)

Usage:
  python scripts/generate_sample_data.py --out ./data/incoming --rows 500
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import string

import pandas as pd


def rand_address() -> str:
    num = random.randint(100, 9999)
    street = random.choice(["Main", "Oak", "Pine", "Cedar", "Maple", "Elm"])
    suffix = random.choice(["St", "Ave", "Rd", "Ln", "Blvd"])
    return f"{num} {street} {suffix}"


def make_base(rows: int) -> pd.DataFrame:
    counties = ["Baca", "Prowers", "Las Animas", "Kiowa", "Otero"]
    land_uses = ["Ag", "Residential", "Commercial", "Industrial", "Vacant"]
    start = datetime.now(timezone.utc) - timedelta(days=30)

    data = []
    for i in range(rows):
        parcel_id = f"{random.randint(1000000, 9999999)}-{random.randint(10, 99)}"
        county = random.choice(counties)
        assessed_value = round(max(0, random.gauss(180000, 90000)), 2)
        row = {
            "parcel_id": parcel_id,
            "county": county,
            "situs_address": rand_address(),
            "assessed_value": assessed_value if random.random() > 0.05 else None,
            "land_use": random.choice(land_uses),
            "updated_at": (start + timedelta(minutes=i)).isoformat(),
        }
        data.append(row)

    df = pd.DataFrame(data)
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Output directory (e.g., ./data/incoming)")
    parser.add_argument("--rows", type=int, default=500)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    base = make_base(args.rows)
    base_path = out / "parcels_baseline.xlsx"
    base.to_excel(base_path, index=False)

    drift = base.copy()
    drift["zoning"] = [random.choice(["A", "R1", "R2", "C1", "M"]) for _ in range(len(drift))]
    drift_path = out / "parcels_drift_add_column.xlsx"
    drift.to_excel(drift_path, index=False)

    bad = base.copy()
    # violate quality: negative assessed values and missing required updated_at
    bad.loc[0:10, "assessed_value"] = -100
    bad.loc[0:25, "updated_at"] = None
    bad_path = out / "parcels_bad_quality.xlsx"
    bad.to_excel(bad_path, index=False)

    print(f"Wrote:\n- {base_path}\n- {drift_path}\n- {bad_path}")


if __name__ == "__main__":
    random.seed(7)
    main()
