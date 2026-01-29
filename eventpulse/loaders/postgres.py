from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import pandas as pd
import psycopg2
import psycopg2.extras

from ..config import settings
from ..contracts import DatasetContract
from ..db import get_conn, now_utc


_TYPE_MAP = {
    "string": "TEXT",
    "text": "TEXT",
    "integer": "BIGINT",
    "int": "BIGINT",
    "number": "DOUBLE PRECISION",
    "float": "DOUBLE PRECISION",
    "double": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "datetime": "TIMESTAMPTZ",
    "timestamp": "TIMESTAMPTZ",
}


def _sql_type(spec: Dict[str, Any]) -> str:
    t = (spec.get("type") or "string").lower()
    return _TYPE_MAP.get(t, "TEXT")


def ensure_curated_table(contract: DatasetContract) -> str:
    table = f"curated_{contract.dataset}"
    cols_sql: List[str] = []
    for col, spec in contract.columns.items():
        cols_sql.append(f"{_quote_ident(col)} {_sql_type(spec)}")

    # lineage metadata columns
    cols_sql.append("_ingestion_id UUID NOT NULL")
    cols_sql.append("_loaded_at TIMESTAMPTZ NOT NULL")
    cols_sql.append("_source_sha256 TEXT NOT NULL")

    pk_sql = ""
    if contract.primary_key:
        pk_sql = f", PRIMARY KEY ({_quote_ident(contract.primary_key)})"

    create_sql = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(cols_sql)}{pk_sql});"

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(create_sql)

    return table


def upsert_curated(
    contract: DatasetContract,
    df: pd.DataFrame,
    ingestion_id: str,
    source_sha256: str,
) -> int:
    table = ensure_curated_table(contract)

    # Ensure expected columns exist
    cols = list(contract.columns.keys())
    for c in cols:
        if c not in df.columns:
            df[c] = None

    df = df[cols].copy()

    # Coerce datetimes if specified
    for col, spec in contract.columns.items():
        t = (spec.get("type") or "").lower()
        if t in ("datetime", "timestamp") and col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    # Add lineage columns
    df["_ingestion_id"] = ingestion_id
    df["_loaded_at"] = now_utc()
    df["_source_sha256"] = source_sha256

    # Replace NaN with None
    df = df.where(pd.notnull(df), None)

    all_cols = cols + ["_ingestion_id", "_loaded_at", "_source_sha256"]

    rows = [tuple(df[c].iloc[i] for c in all_cols) for i in range(len(df))]

    if not rows:
        return 0

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            insert_cols_sql = ", ".join(_quote_ident(c) for c in all_cols)
            values_template = "(" + ", ".join(["%s"] * len(all_cols)) + ")"

            if contract.primary_key:
                pk = contract.primary_key
                update_cols = [c for c in all_cols if c != pk]
                update_sql = ", ".join(f"{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}" for c in update_cols)
                sql = f"INSERT INTO {table} ({insert_cols_sql}) VALUES %s ON CONFLICT ({_quote_ident(pk)}) DO UPDATE SET {update_sql};"
            else:
                sql = f"INSERT INTO {table} ({insert_cols_sql}) VALUES %s;"

            psycopg2.extras.execute_values(cur, sql, rows, page_size=500)

    return len(rows)


def sample_curated(dataset: str, limit: int = 20) -> List[Dict[str, Any]]:
    table = f"curated_{dataset}"
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} ORDER BY _loaded_at DESC LIMIT %s;", (limit,))
            return [dict(r) for r in cur.fetchall()]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
