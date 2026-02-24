from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class ParcelSale:
    parcel_id: str
    county: str
    situs_address: str
    city: str
    state: str
    zip: str
    lat: float
    lon: float
    sale_date: str
    recording_date: str
    sale_price: int
    deed_type: str
    doc_number: str
    book: str
    page: str
    grantor: str
    grantee: str
    year_built: int
    bedrooms: int
    bathrooms: float
    building_sqft: int
    lot_sqft: int
    assessed_value: float
    land_use: str
    updated_at: str


SPRINGFIELD_CO_CENTER: Tuple[float, float] = (37.4083, -102.6146)
# Rough bounding box around Springfield, CO (demo only).
SPRINGFIELD_CO_BBOX: Dict[str, float] = {
    "lat_min": 37.375,
    "lat_max": 37.440,
    "lon_min": -102.660,
    "lon_max": -102.565,
}


_STREETS = [
    "Main St",
    "2nd St",
    "3rd St",
    "4th St",
    "5th St",
    "Pine St",
    "Maple St",
    "Oak St",
    "Cedar St",
    "Elm St",
    "Walnut St",
    "Spruce St",
]

_DEED_TYPES = [
    "Warranty Deed",
    "Quitclaim Deed",
    "Special Warranty Deed",
    "Trustee Deed",
]

_LAND_TYPE_CONFIG: Dict[str, Dict[str, float]] = {
    "grassland": {
        "weight": 0.30,
        "target_price_per_acre": 600.0,
    },
    "dry farmland": {
        "weight": 0.35,
        "target_price_per_acre": 800.0,
    },
    "irrigated farmland": {
        "weight": 0.35,
        "target_price_per_acre": 1_500.0,
    },
}

_LAST_NAMES = [
    "Anderson",
    "Baker",
    "Carter",
    "Davis",
    "Edwards",
    "Foster",
    "Garcia",
    "Harris",
    "Johnson",
    "King",
    "Lopez",
    "Miller",
    "Nguyen",
    "Ortiz",
    "Patel",
    "Reed",
    "Smith",
    "Turner",
    "Walker",
    "Young",
]

_FIRST_NAMES = [
    "Alex",
    "Avery",
    "Blake",
    "Casey",
    "Drew",
    "Emerson",
    "Hayden",
    "Jordan",
    "Kai",
    "Logan",
    "Morgan",
    "Parker",
    "Quinn",
    "Riley",
    "Rowan",
    "Sam",
    "Taylor",
]


def _iso(d: date) -> str:
    return d.isoformat()


def _iso_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def _rand_book_page(rng: random.Random) -> Tuple[str, str]:
    book = str(rng.randint(120, 399))
    page = str(rng.randint(1, 999)).zfill(3)
    return book, page


def _rand_doc_number(rng: random.Random, sale_date: date) -> str:
    # Recorder-style doc number, purely synthetic.
    suffix = rng.randint(10000, 99999)
    return f"{sale_date.year}-{suffix}"


def generate_recorder_sales(limit: int = 200, seed: int = 81073, parcel_id_prefix: str = "BACA") -> Dict[str, Any]:
    """Generate fake county-recorder-style sales near Springfield, CO.

    Data is synthetic (no owners, no real sale prices). Location is anchored to
    Springfield, CO to make the map demo feel real.
    """
    rng = random.Random(seed)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=365 * 12)

    rows: List[ParcelSale] = []
    land_types = list(_LAND_TYPE_CONFIG.keys())
    land_weights = [_LAND_TYPE_CONFIG[k]["weight"] for k in land_types]

    for i in range(limit):
        lat = rng.uniform(SPRINGFIELD_CO_BBOX["lat_min"], SPRINGFIELD_CO_BBOX["lat_max"])
        lon = rng.uniform(SPRINGFIELD_CO_BBOX["lon_min"], SPRINGFIELD_CO_BBOX["lon_max"])

        street = rng.choice(_STREETS)
        house_number = rng.randint(100, 999)
        situs = f"{house_number} {street}"

        sale_dt = start + timedelta(days=rng.randint(0, (today - start).days))
        recording_dt = sale_dt + timedelta(days=rng.randint(0, 14))

        land_type = rng.choices(land_types, weights=land_weights, k=1)[0]
        land_cfg = _LAND_TYPE_CONFIG[land_type]
        target_price_per_acre = land_cfg["target_price_per_acre"] * rng.uniform(0.88, 1.12)

        year_built = rng.randint(1950, 2024)
        bedrooms = rng.randint(2, 5)
        bathrooms = rng.choice([1.0, 1.5, 2.0, 2.5, 3.0])
        building_sqft = rng.randint(900, 5000)
        price_per_sf = rng.uniform(25.0, 300.0)
        price = int(max(60_000, building_sqft * price_per_sf))
        acres = max(10.0, min(2500.0, price / target_price_per_acre))
        lot_sqft = max(4_000, int(acres * 43_560.0))

        assessed_value = round(price * rng.uniform(0.80, 1.20), 2)

        deed_type = rng.choice(_DEED_TYPES)
        book, page = _rand_book_page(rng)
        doc_number = _rand_doc_number(rng, sale_dt)

        grantor = _rand_name(rng)
        grantee = _rand_name(rng)

        parcel_id = f"{parcel_id_prefix}-{i + 1:05d}"
        updated_at = datetime.combine(recording_dt, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
            hours=rng.randint(1, 72)
        )

        rows.append(
            ParcelSale(
                parcel_id=parcel_id,
                county="Baca",
                situs_address=situs,
                city="Springfield",
                state="CO",
                zip="81073",
                lat=lat,
                lon=lon,
                sale_date=_iso(sale_dt),
                recording_date=_iso(recording_dt),
                sale_price=price,
                deed_type=deed_type,
                doc_number=doc_number,
                book=book,
                page=page,
                grantor=grantor,
                grantee=grantee,
                year_built=year_built,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                building_sqft=building_sqft,
                lot_sqft=lot_sqft,
                assessed_value=assessed_value,
                land_use=land_type,
                updated_at=_iso_dt(updated_at),
            )
        )

    return {
        "center": {"lat": SPRINGFIELD_CO_CENTER[0], "lon": SPRINGFIELD_CO_CENTER[1]},
        "bbox": dict(SPRINGFIELD_CO_BBOX),
        "rows": [asdict(r) for r in rows],
    }
