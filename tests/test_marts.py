from __future__ import annotations


from eventpulse.loaders.postgres import list_dataset_marts


def test_edge_telemetry_marts_include_alerts() -> None:
    marts = list_dataset_marts("edge_telemetry")
    names = {m["name"] for m in marts}

    # Existing marts
    assert "device_status" in names
    assert "device_geo_status" in names
    assert "latest_by_device" in names
    assert "geo_points" in names

    # Field ops upgrades
    assert "device_alerts" in names
    assert "latest_readings" in names
