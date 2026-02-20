from __future__ import annotations

import pytest

from eventpulse.contracts import parse_contract_yaml


VALID = """
dataset: parcels
description: Parcel registry
drift_policy: warn
primary_key: parcel_id
columns:
  parcel_id:
    type: string
    required: true
    unique: true
  owner_name:
    type: string
  assessed_value:
    type: number
quality:
  max_null_fraction:
    owner_name: 0.8
"""


def test_parse_contract_yaml_valid() -> None:
    c = parse_contract_yaml(VALID)
    assert c.dataset == "parcels"
    assert "parcel_id" in c.columns
    assert c.primary_key == "parcel_id"


def test_contract_rejects_bad_column_name() -> None:
    bad = """
dataset: parcels
columns:
  Parcel-ID:
    type: string
"""
    with pytest.raises(ValueError):
        parse_contract_yaml(bad)


def test_contract_rejects_unknown_quality_column() -> None:
    bad = """
dataset: parcels
columns:
  parcel_id:
    type: string
quality:
  max_null_fraction:
    missing_col: 0.2
"""
    with pytest.raises(ValueError):
        parse_contract_yaml(bad)


def test_contract_rejects_bad_drift_policy() -> None:
    bad = """
dataset: parcels
columns:
  parcel_id:
    type: string
drift_policy: explode
"""
    with pytest.raises(ValueError):
        parse_contract_yaml(bad)


def test_contract_rejects_pk_not_in_columns() -> None:
    bad = """
dataset: parcels
primary_key: parcel_id
columns:
  owner_name:
    type: string
"""
    with pytest.raises(ValueError):
        parse_contract_yaml(bad)
