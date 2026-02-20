import hashlib
from typing import Any, Dict, List

import pandas as pd


def infer_schema(df: pd.DataFrame) -> Dict[str, Any]:
    """Return a stable schema representation for drift detection."""
    cols: List[Dict[str, str]] = []
    for c in df.columns:
        series = df[c]
        dtype = str(series.dtype)
        logical = _logical_type(series)
        cols.append({"name": str(c), "dtype": dtype, "logical_type": logical})
    cols_sorted = sorted(cols, key=lambda x: x["name"])
    return {"columns": cols_sorted, "column_count": len(cols_sorted)}


def schema_hash(schema: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    # stable representation
    for col in schema.get("columns", []):
        h.update(col["name"].encode("utf-8"))
        h.update(col["logical_type"].encode("utf-8"))
    return h.hexdigest()


def _logical_type(series: pd.Series) -> str:
    # A small, practical mapping for drift detection
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"
