from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import yaml

from .config import settings
from .naming import normalize_dataset_name


# Strict-but-practical contract validation keeps ingestion deterministic and secure.
# These rules intentionally mirror dataset naming conventions to prevent:
# - path traversal / filesystem surprises
# - SQL identifier weirdness (for curated tables + marts)
# - schema drift due to casing differences
_COLUMN_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

_ALLOWED_TYPES: Tuple[str, ...] = (
    "string",
    "text",
    "integer",
    "int",
    "number",
    "float",
    "double",
    "boolean",
    "bool",
    "datetime",
    "timestamp",
)

_ALLOWED_DRIFT_POLICIES: Tuple[str, ...] = ("warn", "fail", "allow")


def validate_contract_dict(d: Any) -> Dict[str, Any]:
    if not isinstance(d, dict):
        raise ValueError("Contract YAML must parse to an object/dict.")

    if "dataset" not in d:
        raise ValueError("Contract must include a 'dataset' field.")

    dataset = normalize_dataset_name(str(d["dataset"]))

    description = str(d.get("description") or "")

    columns_raw = d.get("columns") or {}
    if not isinstance(columns_raw, dict) or not columns_raw:
        raise ValueError("Contract must include a non-empty 'columns' mapping.")

    columns: Dict[str, Dict[str, Any]] = {}
    for col_name, spec_raw in columns_raw.items():
        if not isinstance(col_name, str):
            raise ValueError("Column names must be strings.")
        if not _COLUMN_RE.fullmatch(col_name):
            raise ValueError(
                f"Invalid column name {col_name!r}. Use lowercase letters/numbers/underscore, start with a letter, max 63 chars."
            )

        if spec_raw is None:
            spec_raw = {}
        if not isinstance(spec_raw, dict):
            raise ValueError(f"Column spec for {col_name!r} must be an object/dict.")

        spec = dict(spec_raw)

        t = str(spec.get("type") or "string").lower().strip()
        if t not in _ALLOWED_TYPES:
            raise ValueError(f"Unsupported type {t!r} for column {col_name!r}. Allowed: {sorted(set(_ALLOWED_TYPES))}")
        spec["type"] = t

        for bkey in ("required", "unique"):
            if bkey in spec and not isinstance(spec[bkey], bool):
                raise ValueError(f"Column {col_name!r} field {bkey!r} must be boolean.")

        for nkey in ("min", "max"):
            if nkey in spec:
                try:
                    float(spec[nkey])
                except Exception as e:
                    raise ValueError(f"Column {col_name!r} field {nkey!r} must be numeric.") from e

        columns[col_name] = spec

    primary_key = d.get("primary_key")
    if primary_key is not None:
        primary_key = str(primary_key).strip() or None
    if primary_key:
        if primary_key not in columns:
            raise ValueError(f"primary_key {primary_key!r} must be present in columns.")
        # Best practice: PK should be required + unique (not enforced, but can be validated later).

    quality_raw = d.get("quality") or {}
    if not isinstance(quality_raw, dict):
        raise ValueError("'quality' must be an object/dict.")
    quality = dict(quality_raw)

    max_null_fraction = quality.get("max_null_fraction") or {}
    if max_null_fraction:
        if not isinstance(max_null_fraction, dict):
            raise ValueError("'quality.max_null_fraction' must be a mapping of column -> threshold.")
        for col, thr in max_null_fraction.items():
            if col not in columns:
                raise ValueError(f"'quality.max_null_fraction' references unknown column {col!r}.")
            try:
                v = float(thr)
            except Exception as e:
                raise ValueError(f"'quality.max_null_fraction' threshold for {col!r} must be numeric.") from e
            if v < 0.0 or v > 1.0:
                raise ValueError(f"'quality.max_null_fraction' threshold for {col!r} must be between 0 and 1.")

    drift_policy = d.get("drift_policy")
    if drift_policy is not None:
        drift_policy = str(drift_policy).lower().strip() or None
    if drift_policy and drift_policy not in _ALLOWED_DRIFT_POLICIES:
        raise ValueError(f"drift_policy must be one of {list(_ALLOWED_DRIFT_POLICIES)}")

    return {
        "dataset": dataset,
        "description": description,
        "primary_key": primary_key,
        "columns": columns,
        "quality": quality,
        "drift_policy": drift_policy,
    }


def parse_contract_yaml(raw_yaml: str) -> DatasetContract:
    """Parse and validate a contract YAML string."""

    if not (raw_yaml or "").strip():
        raise ValueError("Contract YAML is empty.")

    d = yaml.safe_load(raw_yaml)
    normalized = validate_contract_dict(d)
    return DatasetContract.from_dict(normalized)


@dataclass(frozen=True)
class DatasetContract:
    dataset: str
    description: str
    primary_key: Optional[str]
    columns: Dict[str, Dict[str, Any]]
    quality: Dict[str, Any]
    drift_policy: Optional[str]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DatasetContract":
        # Allow callers to pass either raw dicts or already-normalized dicts.
        normalized = validate_contract_dict(d)
        return DatasetContract(
            dataset=normalized["dataset"],
            description=normalized.get("description", ""),
            primary_key=normalized.get("primary_key"),
            columns=normalized.get("columns", {}) or {},
            quality=normalized.get("quality", {}) or {},
            drift_policy=normalized.get("drift_policy"),
        )


@dataclass(frozen=True)
class ContractLoadResult:
    contract: DatasetContract
    path: str
    sha256: str


def load_contract(dataset: str) -> DatasetContract:
    return load_contract_with_meta(dataset).contract


def load_contract_with_meta(dataset: str) -> ContractLoadResult:
    dataset = normalize_dataset_name(dataset)
    path = os.path.join(settings.contracts_dir, f"{dataset}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Contract not found for dataset '{dataset}' at {path}")

    with open(path, "rb") as f:
        raw = f.read()

    sha = hashlib.sha256(raw).hexdigest()
    d = yaml.safe_load(raw.decode("utf-8"))

    return ContractLoadResult(contract=DatasetContract.from_dict(d), path=path, sha256=sha)
