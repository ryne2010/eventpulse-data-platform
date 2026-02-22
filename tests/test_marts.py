from __future__ import annotations


from eventpulse.loaders.postgres import list_dataset_marts


def test_parcels_marts_include_expected_views() -> None:
    marts = list_dataset_marts("parcels")
    names = {m["name"] for m in marts}

    assert "freshness" in names
    assert "price_stats" in names
    assert "sales_by_year" in names
    assert "sales_by_month" in names
    assert "geo_points" in names
