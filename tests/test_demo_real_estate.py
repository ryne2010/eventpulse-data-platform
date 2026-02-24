from __future__ import annotations

from eventpulse.demo.real_estate import SPRINGFIELD_CO_BBOX, generate_recorder_sales


def test_generate_recorder_sales_contains_expected_land_use_categories() -> None:
    payload = generate_recorder_sales(limit=120, seed=12345)
    rows = payload["rows"]
    assert len(rows) == 120

    land_use_values = {str(r.get("land_use")) for r in rows}
    assert "grassland" in land_use_values
    assert "dry farmland" in land_use_values
    assert "irrigated farmland" in land_use_values


def test_generate_recorder_sales_price_targets_are_in_expected_ranges() -> None:
    payload = generate_recorder_sales(limit=300, seed=81234)
    rows = payload["rows"]

    grouped: dict[str, list[float]] = {"grassland": [], "dry farmland": [], "irrigated farmland": []}
    psf_values: list[float] = []

    for r in rows:
        sale_price = float(r["sale_price"])
        lot_sqft = float(r["lot_sqft"])
        building_sqft = float(r["building_sqft"])
        land_use = str(r["land_use"])

        price_per_acre = sale_price * 43560.0 / lot_sqft
        price_per_sf = sale_price / building_sqft

        if land_use in grouped:
            grouped[land_use].append(price_per_acre)
        psf_values.append(price_per_sf)

    def _median(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0

    med_grass = _median(grouped["grassland"])
    med_dry = _median(grouped["dry farmland"])
    med_irrigated = _median(grouped["irrigated farmland"])

    assert 500 <= med_grass <= 700
    assert 680 <= med_dry <= 920
    assert 1300 <= med_irrigated <= 1700

    assert min(psf_values) >= 25
    assert max(psf_values) <= 300


def test_generate_recorder_sales_rows_align_with_contract_shape() -> None:
    payload = generate_recorder_sales(limit=10, seed=44)
    rows = payload["rows"]
    assert len(rows) == 10

    required = {
        "parcel_id",
        "county",
        "situs_address",
        "city",
        "state",
        "zip",
        "lat",
        "lon",
        "sale_date",
        "recording_date",
        "sale_price",
        "deed_type",
        "doc_number",
        "book",
        "page",
        "grantor",
        "grantee",
        "year_built",
        "bedrooms",
        "bathrooms",
        "building_sqft",
        "lot_sqft",
        "assessed_value",
        "land_use",
        "updated_at",
    }
    assert required.issubset(set(rows[0].keys()))

    for r in rows:
        lat = float(r["lat"])
        lon = float(r["lon"])
        assert SPRINGFIELD_CO_BBOX["lat_min"] <= lat <= SPRINGFIELD_CO_BBOX["lat_max"]
        assert SPRINGFIELD_CO_BBOX["lon_min"] <= lon <= SPRINGFIELD_CO_BBOX["lon_max"]
