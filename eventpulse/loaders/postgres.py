from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

import logging

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from ..contracts import DatasetContract
from ..db import get_conn, now_utc
from ..naming import normalize_dataset_name

logger = logging.getLogger(__name__)


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

_MAX_SAMPLE_LIMIT = 2000


def _clamp_sample_limit(limit: int) -> int:
    """Bound row-sample limits to protect DB queries from oversized values."""

    return max(1, min(int(limit), _MAX_SAMPLE_LIMIT))


def _to_db_scalar(v: Any) -> Any:
    """Normalize pandas/numpy scalars for psycopg2 inserts.

    In particular, convert NaN/NaT/NA to None so nullable integer columns
    don't fail with 'bigint out of range' on cast from NaN.
    """

    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def _sql_type(spec: Dict[str, Any]) -> str:
    t = (spec.get("type") or "string").lower()
    return _TYPE_MAP.get(t, "TEXT")


def ensure_curated_table(contract: DatasetContract) -> str:
    dataset = normalize_dataset_name(contract.dataset)
    table = f"curated_{dataset}"

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

    create_sql = f"CREATE TABLE IF NOT EXISTS {_quote_ident(table)} ({', '.join(cols_sql)}{pk_sql});"

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(create_sql)
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            existing = {r[0] for r in cur.fetchall()}

            desired: List[Tuple[str, str]] = [(c, _sql_type(spec)) for c, spec in contract.columns.items()]
            desired += [
                ("_ingestion_id", "UUID"),
                ("_loaded_at", "TIMESTAMPTZ"),
                ("_source_sha256", "TEXT"),
            ]

            for col, sql_type in desired:
                if col in existing:
                    continue
                cur.execute(f"ALTER TABLE {_quote_ident(table)} ADD COLUMN {_quote_ident(col)} {sql_type};")

            # Best-effort: ensure primary key exists for ON CONFLICT upserts.
            if contract.primary_key:
                pk = contract.primary_key
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = %s
                      AND tc.constraint_type = 'PRIMARY KEY'
                      AND kcu.column_name = %s
                    LIMIT 1;
                    """,
                    (table, pk),
                )
                if cur.fetchone() is None:
                    try:
                        cur.execute(f"ALTER TABLE {_quote_ident(table)} ADD PRIMARY KEY ({_quote_ident(pk)});")
                    except Exception as e:
                        logger.warning(
                            "Failed to add primary key constraint (table may contain duplicates)",
                            extra={"table": table, "pk": pk, "error": str(e)},
                        )

    # Best-effort: ensure marts/views that provide read-optimized aggregates.
    # These are safe to call repeatedly and keep the demo UI snappy.
    try:
        ensure_marts_views(dataset)
    except Exception as e:
        logger.warning(
            "Failed to ensure marts views",
            extra={"dataset": dataset, "error": str(e)},
        )

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
    # Pandas stubs type the replacement value fairly strictly; we intentionally replace
    # NaN/NaT with None so psycopg2 writes SQL NULLs.
    df = df.where(pd.notnull(df), cast(Any, None))

    all_cols = cols + ["_ingestion_id", "_loaded_at", "_source_sha256"]

    rows = [tuple(_to_db_scalar(df[c].iloc[i]) for c in all_cols) for i in range(len(df))]

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
                sql = (
                    f"INSERT INTO {_quote_ident(table)} ({insert_cols_sql}) VALUES %s "
                    f"ON CONFLICT ({_quote_ident(pk)}) DO UPDATE SET {update_sql};"
                )
            else:
                sql = f"INSERT INTO {_quote_ident(table)} ({insert_cols_sql}) VALUES %s;"

            # Provide an explicit template so the generated VALUES clause is deterministic.
            psycopg2.extras.execute_values(cur, sql, rows, template=values_template, page_size=500)

    return len(rows)


def curated_table_exists(dataset: str) -> bool:
    dataset = normalize_dataset_name(dataset)
    table = f"curated_{dataset}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s);", (table,))
            row = cur.fetchone()
            return bool(row and row[0] is not None)


def sample_curated(dataset: str, limit: int = 20) -> List[Dict[str, Any]]:
    dataset = normalize_dataset_name(dataset)
    limit = _clamp_sample_limit(limit)
    table = f"curated_{dataset}"
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {_quote_ident(table)} ORDER BY _loaded_at DESC LIMIT %s;",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def sample_curated_for_ingestion(dataset: str, ingestion_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    dataset = normalize_dataset_name(dataset)
    limit = _clamp_sample_limit(limit)
    table = f"curated_{dataset}"
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {_quote_ident(table)}
                WHERE _ingestion_id = %s
                ORDER BY _loaded_at DESC
                LIMIT %s;
                """,
                (ingestion_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


# -----------------------------
# Marts (read-optimized views)
# -----------------------------


def ensure_marts_views(dataset: str) -> None:
    """Create/refresh read-optimized marts for a dataset.

    These are *views* in Postgres, created best-effort:
    - They make the demo UI feel like a warehouse-backed app.
    - They illustrate the "curated → marts" pattern without requiring dbt.

    NOTE: marts must never break ingestion. If a mart fails to build (e.g. a
    contract removed a referenced column), we log and continue.
    """

    dataset = normalize_dataset_name(dataset)
    curated_table = f"curated_{dataset}"

    freshness_view = f"marts_{dataset}_freshness"

    def _try(cur, sql: str, view_name: str) -> None:
        try:
            cur.execute(sql)
        except Exception:
            logger.warning("Failed to create mart view %s for dataset=%s", view_name, dataset, exc_info=True)

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Generic: freshness + cardinality
            _try(
                cur,
                f"""
                CREATE OR REPLACE VIEW {_quote_ident(freshness_view)} AS
                SELECT
                  COUNT(*)::BIGINT AS row_count,
                  COUNT(DISTINCT _ingestion_id)::BIGINT AS ingestion_count,
                  MAX(_loaded_at) AS last_loaded_at
                FROM {_quote_ident(curated_table)};
                """,
                freshness_view,
            )

            # Dataset-specific marts
            if dataset == "parcels":
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_price_stats")} AS
                    SELECT
                      COUNT(*)::BIGINT AS sales_count,
                      MIN(sale_price) AS min_sale_price,
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY sale_price) AS p25_sale_price,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY sale_price) AS median_sale_price,
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY sale_price) AS p75_sale_price,
                      MAX(sale_price) AS max_sale_price
                    FROM {_quote_ident(curated_table)}
                    WHERE sale_price IS NOT NULL;
                    """,
                    "marts_parcels_price_stats",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_sales_by_year")} AS
                    SELECT
                      EXTRACT(YEAR FROM sale_date)::INT AS year,
                      COUNT(*)::BIGINT AS sales_count,
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY sale_price) AS p25_sale_price,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY sale_price) AS median_sale_price,
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY sale_price) AS p75_sale_price
                    FROM {_quote_ident(curated_table)}
                    WHERE sale_price IS NOT NULL AND sale_date IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1 ASC;
                    """,
                    "marts_parcels_sales_by_year",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_price_per_acre_by_land_type")} AS
                    WITH normalized AS (
                      SELECT
                        CASE
                          WHEN land_use IS NULL OR btrim(land_use) = '' THEN NULL
                          ELSE lower(btrim(land_use))
                        END AS land_use_norm,
                        sale_price,
                        lot_sqft
                      FROM {_quote_ident(curated_table)}
                      WHERE sale_price IS NOT NULL
                        AND lot_sqft IS NOT NULL
                        AND lot_sqft > 0
                    ),
                    base AS (
                      SELECT
                        CASE
                          WHEN land_use_norm IN ('grassland', 'dry farmland', 'irrigated farmland') THEN land_use_norm
                          ELSE NULL
                        END AS land_type,
                        (sale_price * 43560.0 / NULLIF(lot_sqft::DOUBLE PRECISION, 0.0)) AS price_per_acre
                      FROM normalized
                    )
                    SELECT
                      land_type,
                      COUNT(*)::BIGINT AS sales_count,
                      AVG(price_per_acre) AS avg_price_per_acre,
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY price_per_acre) AS p25_price_per_acre,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY price_per_acre) AS median_price_per_acre,
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY price_per_acre) AS p75_price_per_acre
                    FROM base
                    WHERE land_type IS NOT NULL
                    GROUP BY 1
                    ORDER BY median_price_per_acre DESC NULLS LAST, land_type ASC;
                    """,
                    "marts_parcels_price_per_acre_by_land_type",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_price_per_sf_by_year_built")} AS
                    WITH base AS (
                      SELECT
                        year_built::INT AS year_built,
                        (sale_price / NULLIF(building_sqft::DOUBLE PRECISION, 0.0)) AS price_per_sf
                      FROM {_quote_ident(curated_table)}
                      WHERE sale_price IS NOT NULL
                        AND building_sqft IS NOT NULL
                        AND building_sqft > 0
                        AND year_built IS NOT NULL
                    )
                    SELECT
                      year_built,
                      COUNT(*)::BIGINT AS sales_count,
                      AVG(price_per_sf) AS avg_price_per_sf,
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY price_per_sf) AS p25_price_per_sf,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY price_per_sf) AS median_price_per_sf,
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY price_per_sf) AS p75_price_per_sf
                    FROM base
                    GROUP BY 1
                    ORDER BY 1 ASC;
                    """,
                    "marts_parcels_price_per_sf_by_year_built",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_price_per_sf_by_sale_year")} AS
                    WITH base AS (
                      SELECT
                        EXTRACT(YEAR FROM sale_date)::INT AS sale_year,
                        (sale_price / NULLIF(building_sqft::DOUBLE PRECISION, 0.0)) AS price_per_sf
                      FROM {_quote_ident(curated_table)}
                      WHERE sale_price IS NOT NULL
                        AND sale_date IS NOT NULL
                        AND building_sqft IS NOT NULL
                        AND building_sqft > 0
                    )
                    SELECT
                      sale_year,
                      COUNT(*)::BIGINT AS sales_count,
                      AVG(price_per_sf) AS avg_price_per_sf,
                      percentile_cont(0.25) WITHIN GROUP (ORDER BY price_per_sf) AS p25_price_per_sf,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY price_per_sf) AS median_price_per_sf,
                      percentile_cont(0.75) WITHIN GROUP (ORDER BY price_per_sf) AS p75_price_per_sf
                    FROM base
                    GROUP BY 1
                    ORDER BY 1 ASC;
                    """,
                    "marts_parcels_price_per_sf_by_sale_year",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_sales_by_month")} AS
                    SELECT
                      date_trunc('month', sale_date) AS month,
                      COUNT(*)::BIGINT AS sales_count,
                      percentile_cont(0.50) WITHIN GROUP (ORDER BY sale_price) AS median_sale_price
                    FROM {_quote_ident(curated_table)}
                    WHERE sale_price IS NOT NULL AND sale_date IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1 ASC;
                    """,
                    "marts_parcels_sales_by_month",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_parcels_geo_points")} AS
                    SELECT
                      parcel_id,
                      sale_date,
                      sale_price,
                      county,
                      city,
                      state,
                      lat,
                      lon
                    FROM {_quote_ident(curated_table)}
                    WHERE lat IS NOT NULL AND lon IS NOT NULL;
                    """,
                    "marts_parcels_geo_points",
                )


def view_exists(view_name: str) -> bool:
    """Return True if a view/table exists in the public schema."""

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s);", (view_name,))
            row = cur.fetchone()
            return bool(row and row[0] is not None)


def sample_view(view_name: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Fetch rows from a view (or table) in a safe, read-only way."""

    limit = _clamp_sample_limit(limit)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {_quote_ident(view_name)} LIMIT %s;", (limit,))
            return [dict(r) for r in cur.fetchall()]


def sample_parcels_sales_for_bucket(dimension: str, bucket: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Fetch parcel sale rows for an analytics bucket (dashboard drill-down)."""

    dim = str(dimension or "").strip().lower()
    limit = _clamp_sample_limit(limit)

    if dim not in {"land_type", "year_built", "sale_year"}:
        raise ValueError("dimension must be one of: land_type, year_built, sale_year")

    curated_table = _quote_ident("curated_parcels")
    base_sql = f"""
        WITH base AS (
          SELECT
            parcel_id,
            sale_date,
            EXTRACT(YEAR FROM sale_date)::INT AS sale_year,
            sale_price,
            year_built::INT AS year_built,
            building_sqft::BIGINT AS building_sqft,
            lot_sqft::BIGINT AS lot_sqft,
            CASE
              WHEN land_use IS NULL OR btrim(land_use) = '' THEN NULL
              ELSE lower(btrim(land_use))
            END AS land_use_norm,
            CASE
              WHEN land_use IS NULL OR btrim(land_use) = '' THEN NULL
              ELSE lower(btrim(land_use))
            END AS land_use,
            (sale_price * 43560.0 / NULLIF(lot_sqft::DOUBLE PRECISION, 0.0)) AS price_per_acre,
            (sale_price / NULLIF(building_sqft::DOUBLE PRECISION, 0.0)) AS price_per_sf
          FROM {curated_table}
          WHERE sale_price IS NOT NULL
        ),
        normalized AS (
          SELECT
            parcel_id,
            sale_date,
            sale_year,
            sale_price,
            year_built,
            building_sqft,
            lot_sqft,
            CASE
              WHEN land_use_norm IN ('grassland', 'dry farmland', 'irrigated farmland') THEN land_use_norm
              ELSE NULL
            END AS land_type,
            price_per_acre,
            price_per_sf
          FROM base
        )
    """

    params: Tuple[Any, ...]
    if dim == "land_type":
        land_type = str(bucket or "").strip().lower()
        if land_type not in {"grassland", "dry farmland", "irrigated farmland"}:
            raise ValueError("bucket must be one of: grassland, dry farmland, irrigated farmland")
        sql = (
            base_sql
            + """
            SELECT
              parcel_id,
              sale_date,
              sale_year,
              sale_price,
              year_built,
              building_sqft,
              lot_sqft,
              land_type,
              price_per_acre,
              price_per_sf
            FROM normalized
            WHERE land_type = %s
            ORDER BY sale_date DESC NULLS LAST, parcel_id ASC
            LIMIT %s;
            """
        )
        params = (land_type, limit)
    elif dim == "year_built":
        try:
            year_built = int(str(bucket).strip())
        except Exception as e:
            raise ValueError("bucket must be an integer year for dimension=year_built") from e
        sql = (
            base_sql
            + """
            SELECT
              parcel_id,
              sale_date,
              sale_year,
              sale_price,
              year_built,
              building_sqft,
              lot_sqft,
              land_type,
              price_per_acre,
              price_per_sf
            FROM normalized
            WHERE year_built = %s
              AND price_per_sf IS NOT NULL
            ORDER BY sale_date DESC NULLS LAST, parcel_id ASC
            LIMIT %s;
            """
        )
        params = (year_built, limit)
    else:
        try:
            sale_year = int(str(bucket).strip())
        except Exception as e:
            raise ValueError("bucket must be an integer year for dimension=sale_year") from e
        sql = (
            base_sql
            + """
            SELECT
              parcel_id,
              sale_date,
              sale_year,
              sale_price,
              year_built,
              building_sqft,
              lot_sqft,
              land_type,
              price_per_acre,
              price_per_sf
            FROM normalized
            WHERE sale_year = %s
              AND price_per_sf IS NOT NULL
            ORDER BY sale_date DESC NULLS LAST, parcel_id ASC
            LIMIT %s;
            """
        )
        params = (sale_year, limit)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def list_dataset_marts(dataset: str) -> List[Dict[str, Any]]:
    """Return the available marts for a dataset.

    The API layer uses this to power the dataset detail UI.
    """

    dataset = normalize_dataset_name(dataset)

    marts: List[Dict[str, Any]] = [
        {
            "name": "freshness",
            "view": f"marts_{dataset}_freshness",
            "description": "Row counts + last load timestamp",
        }
    ]

    if dataset == "parcels":
        marts += [
            {
                "name": "price_stats",
                "view": "marts_parcels_price_stats",
                "description": "Global price distribution metrics",
            },
            {
                "name": "sales_by_year",
                "view": "marts_parcels_sales_by_year",
                "description": "Sales count + price percentiles by year",
            },
            {
                "name": "price_per_acre_by_land_type",
                "view": "marts_parcels_price_per_acre_by_land_type",
                "description": "Price-per-acre distribution grouped by land type",
            },
            {
                "name": "price_per_sf_by_year_built",
                "view": "marts_parcels_price_per_sf_by_year_built",
                "description": "Price-per-square-foot grouped by year built",
            },
            {
                "name": "price_per_sf_by_sale_year",
                "view": "marts_parcels_price_per_sf_by_sale_year",
                "description": "Price-per-square-foot grouped by sale year",
            },
            {
                "name": "sales_by_month",
                "view": "marts_parcels_sales_by_month",
                "description": "Sales count + median price by month",
            },
            {
                "name": "geo_points",
                "view": "marts_parcels_geo_points",
                "description": "Lat/Lon points for lightweight mapping in the UI",
            },
        ]

    return marts


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
