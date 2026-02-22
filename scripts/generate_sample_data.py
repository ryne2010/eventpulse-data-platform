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

    print("Wrote:")
    for p in [
        baseline_path,
        drift_add_path,
        drift_type_path,
        qfail_path,
    ]:
        print(" -", p)


if __name__ == "__main__":
    main()
