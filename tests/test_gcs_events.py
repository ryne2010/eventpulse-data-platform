from __future__ import annotations

from eventpulse.gcs_events import build_raw_object_name, is_valid_sha256_hex, parse_raw_object_name


def test_is_valid_sha256_hex() -> None:
    assert is_valid_sha256_hex("a" * 64)
    assert is_valid_sha256_hex("A" * 64)
    assert not is_valid_sha256_hex("a" * 63)
    assert not is_valid_sha256_hex("g" * 64)


def test_build_and_parse_roundtrip_with_simple_prefix() -> None:
    sha = "b" * 64
    obj = build_raw_object_name(raw_prefix="raw", dataset="parcels", day="2026-02-18", sha256=sha, ext=".xlsx")
    assert obj == f"raw/parcels/2026-02-18/{sha}.xlsx"

    ref = parse_raw_object_name(raw_prefix="raw", object_name=obj)
    assert ref is not None
    assert ref.dataset == "parcels"
    assert ref.day == "2026-02-18"
    assert ref.sha256 == sha
    assert ref.ext == ".xlsx"


def test_build_and_parse_roundtrip_with_nested_prefix() -> None:
    sha = "c" * 64
    obj = build_raw_object_name(raw_prefix="raw/dev", dataset="events", day="2026-02-18", sha256=sha, ext="csv")
    assert obj == f"raw/dev/events/2026-02-18/{sha}.csv"

    ref = parse_raw_object_name(raw_prefix="raw/dev", object_name=obj)
    assert ref is not None
    assert ref.dataset == "events"
    assert ref.day == "2026-02-18"
    assert ref.sha256 == sha
    assert ref.ext == ".csv"


def test_parse_rejects_non_matching_prefix() -> None:
    sha = "d" * 64
    obj = f"raw/prod/parcels/2026-02-18/{sha}.xlsx"
    assert parse_raw_object_name(raw_prefix="raw/dev", object_name=obj) is None


def test_parse_rejects_non_sha_filenames() -> None:
    obj = "raw/dev/parcels/2026-02-18/notasha.xlsx"
    assert parse_raw_object_name(raw_prefix="raw/dev", object_name=obj) is None


def test_parse_rejects_bad_day_partition() -> None:
    sha = "e" * 64
    obj = f"raw/dev/parcels/2026_02_18/{sha}.xlsx"
    assert parse_raw_object_name(raw_prefix="raw/dev", object_name=obj) is None
