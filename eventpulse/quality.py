from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .contracts import DatasetContract


@dataclass
class QualityResult:
    passed: bool
    errors: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]


def validate_df(df: pd.DataFrame, contract: DatasetContract) -> QualityResult:
    errors: List[str] = []
    warnings: List[str] = []
    metrics: Dict[str, Any] = {}

    # normalize column names: keep original, but we validate exact names
    expected_cols = contract.columns.keys()

    # Required columns
    required = [c for c, spec in contract.columns.items() if spec.get("required", False)]
    missing_required = [c for c in required if c not in df.columns]
    if missing_required:
        errors.append(f"Missing required columns: {missing_required}")

    # Unexpected columns (not an error, drift handles separately)
    unexpected = [c for c in df.columns if c not in expected_cols]
    if unexpected:
        warnings.append(f"Unexpected columns present: {unexpected}")

    # Type checks (best-effort)
    for col, spec in contract.columns.items():
        if col not in df.columns:
            continue
        expected_type = (spec.get("type") or "").lower()
        if not expected_type:
            continue

        series = df[col]
        # empty column -> skip strict typing, but still counted in null metrics
        if series.dropna().empty:
            continue

        if expected_type in ("string", "text"):
            # allow anything
            pass
        elif expected_type in ("integer", "int"):
            if not (pd.api.types.is_integer_dtype(series) or _looks_like_int(series)):
                errors.append(f"Column '{col}' expected integer-like values.")
        elif expected_type in ("number", "float", "double"):
            if not (pd.api.types.is_numeric_dtype(series) or _looks_like_number(series)):
                errors.append(f"Column '{col}' expected numeric values.")
        elif expected_type in ("datetime", "timestamp"):
            if not pd.api.types.is_datetime64_any_dtype(series):
                # attempt parse
                parsed = pd.to_datetime(series, errors="coerce", utc=True)
                if parsed.isna().mean() > 0.2:
                    errors.append(f"Column '{col}' expected datetime values.")
                else:
                    df[col] = parsed
        elif expected_type in ("boolean", "bool"):
            if not (pd.api.types.is_bool_dtype(series) or _looks_like_bool(series)):
                errors.append(f"Column '{col}' expected boolean values.")
        else:
            warnings.append(f"Unknown expected type '{expected_type}' for column '{col}' (skipped strict check).")

        # min/max checks for numeric
        if expected_type in ("integer", "int", "number", "float", "double") and col in df.columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if "min" in spec:
                min_v = float(spec["min"])
                if (numeric.dropna() < min_v).any():
                    errors.append(f"Column '{col}' has values < min ({min_v}).")
            if "max" in spec:
                max_v = float(spec["max"])
                if (numeric.dropna() > max_v).any():
                    errors.append(f"Column '{col}' has values > max ({max_v}).")

    # Uniqueness
    for col, spec in contract.columns.items():
        if col not in df.columns:
            continue
        if spec.get("unique", False):
            dupes = df[col].duplicated(keep=False)
            if dupes.any():
                errors.append(f"Column '{col}' has duplicate values but is marked unique.")

    # Primary key uniqueness if provided
    if contract.primary_key and contract.primary_key in df.columns:
        pk = contract.primary_key
        if df[pk].duplicated(keep=False).any():
            errors.append(f"Primary key '{pk}' contains duplicates.")

    # Null thresholds
    max_null_fraction = (contract.quality.get("max_null_fraction") or {}) if contract.quality else {}
    null_fracs: Dict[str, float] = {}
    for col, threshold in max_null_fraction.items():
        if col not in df.columns:
            continue
        frac = float(df[col].isna().mean())
        null_fracs[col] = frac
        if frac > float(threshold):
            errors.append(f"Column '{col}' null fraction {frac:.2%} exceeds threshold {float(threshold):.2%}.")
    metrics["null_fractions"] = null_fracs
    metrics["row_count"] = int(len(df))
    metrics["column_count"] = int(len(df.columns))

    return QualityResult(passed=(len(errors) == 0), errors=errors, warnings=warnings, metrics=metrics)


def _looks_like_number(series: pd.Series) -> bool:
    try:
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.notna().mean() > 0.8
    except Exception:
        return False


def _looks_like_int(series: pd.Series) -> bool:
    try:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().mean() <= 0.8:
            return False
        # int-like if all decimals are .0
        frac = (numeric.dropna() % 1.0)
        return (frac < 1e-9).all()
    except Exception:
        return False


def _looks_like_bool(series: pd.Series) -> bool:
    s = series.dropna().astype(str).str.lower().str.strip()
    if s.empty:
        return True
    allowed = {"true", "false", "1", "0", "yes", "no", "y", "n"}
    return s.isin(list(allowed)).mean() > 0.8
