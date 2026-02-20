from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

import logging

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from ..config import settings
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

    def _to_python(v: Any) -> Any:
        # psycopg2 can't adapt numpy scalar types (e.g., numpy.int64) directly.
        if v is None:
            return None
        if isinstance(v, np.generic):
            return v.item()
        if isinstance(v, pd.Timestamp):
            return v.to_pydatetime()
        return v

    rows = [tuple(_to_python(df[c].iloc[i]) for c in all_cols) for i in range(len(df))]

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


def sample_edge_telemetry_for_device(device_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Return recent curated telemetry rows for a given device.

    This powers the field-ops device detail view in the UI.

    Notes
    - Only valid for the built-in demo dataset `edge_telemetry`.
    - Uses ORDER BY ts DESC when present (falling back to _loaded_at).
    """

    did = str(device_id or "").strip()
    if not did:
        raise ValueError("device_id is required")

    limit = max(1, min(int(limit), 2000))
    table = "curated_edge_telemetry"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {_quote_ident(table)}
                WHERE device_id = %s
                ORDER BY ts DESC NULLS LAST, _loaded_at DESC
                LIMIT %s;
                """,
                (did, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def sample_edge_latest_readings_for_device(device_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Return the latest scored readings (one row per sensor) for a given device.

    This is sourced from the mart view:

      marts_edge_telemetry_latest_readings

    Why this exists
    - Avoids duplicating alert scoring logic in the UI.
    - Keeps device detail pages fast (<= sensors, not raw event stream).

    Notes
    - Only valid for the built-in demo dataset `edge_telemetry`.
    - If the mart/view doesn't exist yet (no ingestions processed), the API
      returns an empty list.
    """

    did = str(device_id or "").strip()
    if not did:
        raise ValueError("device_id is required")

    limit = max(1, min(int(limit), 2000))
    view = "marts_edge_telemetry_latest_readings"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {_quote_ident(view)}
                WHERE device_id = %s
                ORDER BY severity_num DESC, ts DESC NULLS LAST, sensor
                LIMIT %s;
                """,
                (did, limit),
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

            if dataset == "edge_telemetry":
                # Field ops tuning: offline threshold (used by device_status mart).
                try:
                    offline_seconds = int(getattr(settings, "edge_offline_threshold_seconds", 600) or 600)
                except Exception:
                    offline_seconds = 600
                # Clamp to a sane range (avoid negative intervals / footguns).
                offline_seconds = max(60, min(offline_seconds, 7 * 24 * 3600))

                # Performance hygiene for time-series edge telemetry.
                #
                # These indexes keep the demo UI snappy and are also helpful for
                # production workloads (device rollups, latest-per-sensor queries,
                # and alerting views).
                try:
                    _try(
                        cur,
                        f"""
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"idx_{curated_table}_device_ts")} 
                        ON {_quote_ident(curated_table)} (device_id, ts DESC);
                        """,
                        f"idx_{curated_table}_device_ts",
                    )
                    _try(
                        cur,
                        f"""
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"idx_{curated_table}_device_sensor_ts")} 
                        ON {_quote_ident(curated_table)} (device_id, sensor, ts DESC);
                        """,
                        f"idx_{curated_table}_device_sensor_ts",
                    )
                except Exception:
                    # Never fail ingestion due to index creation.
                    pass

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_latest_by_device")} AS
                    SELECT DISTINCT ON (device_id)
                      device_id,
                      ts AS last_event_ts,
                      event_type,
                      sensor,
                      value,
                      units,
                      lat,
                      lon,
                      battery_v,
                      rssi_dbm,
                      firmware_version,
                      status,
                      message,
                      _loaded_at,
                      _ingestion_id
                    FROM {_quote_ident(curated_table)}
                    ORDER BY device_id, ts DESC NULLS LAST, _loaded_at DESC;
                    """,
                    "marts_edge_telemetry_latest_by_device",
                )

                # Latest reading per (device_id, sensor) + a lightweight alert scoring model.
                #
                # Notes:
                # - This is intentionally simple and deterministic.
                # - Thresholds are pragmatic defaults for demos and field ops bring-up.
                # - If you need configurable thresholds per site/device, evolve this into a
                #   table-driven model (e.g., device_metadata -> thresholds JSON) or push it
                #   into a dedicated alerting service.
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_latest_readings")} AS
                    WITH latest AS (
                      SELECT DISTINCT ON (device_id, sensor)
                        device_id,
                        sensor,
                        ts,
                        value,
                        units,
                        lat,
                        lon,
                        battery_v,
                        rssi_dbm,
                        firmware_version,
                        status,
                        message,
                        _loaded_at,
                        _ingestion_id
                      FROM {_quote_ident(curated_table)}
                      WHERE event_type = 'reading'
                      ORDER BY device_id, sensor, ts DESC NULLS LAST, _loaded_at DESC
                    ),
                    scored AS (
                      SELECT
                        l.*,
                        -- numeric severity for easy aggregation
                        CASE
                          WHEN sensor = 'oil_pressure_psi' AND value < 15 THEN 2
                          WHEN sensor = 'oil_pressure_psi' AND value < 25 THEN 1

                          WHEN sensor = 'water_pressure_psi' AND value < 30 THEN 2
                          WHEN sensor = 'water_pressure_psi' AND value < 40 THEN 1
                          WHEN sensor = 'water_pressure_psi' AND value > 130 THEN 1

                          WHEN sensor = 'oil_life_pct' AND value < 10 THEN 2
                          WHEN sensor = 'oil_life_pct' AND value < 20 THEN 1

                          WHEN sensor = 'oil_level_pct' AND value < 10 THEN 2
                          WHEN sensor = 'oil_level_pct' AND value < 20 THEN 1

                          WHEN sensor = 'drip_oil_level_pct' AND value > 70 THEN 2
                          WHEN sensor = 'drip_oil_level_pct' AND value > 40 THEN 1

                          WHEN sensor = 'temp_c' AND value > 80 THEN 2
                          WHEN sensor = 'temp_c' AND value > 60 THEN 1

                          WHEN sensor = 'humidity_pct' AND value > 98 THEN 2
                          WHEN sensor = 'humidity_pct' AND value > 90 THEN 1

                          WHEN sensor = 'vibration_g' AND value > 6 THEN 2
                          WHEN sensor = 'vibration_g' AND value > 4 THEN 1
                          ELSE 0
                        END AS severity_num,
                        CASE
                          WHEN sensor = 'oil_pressure_psi' AND value < 15 THEN 'oil_pressure_critical_low'
                          WHEN sensor = 'oil_pressure_psi' AND value < 25 THEN 'oil_pressure_low'

                          WHEN sensor = 'water_pressure_psi' AND value < 30 THEN 'water_pressure_critical_low'
                          WHEN sensor = 'water_pressure_psi' AND value < 40 THEN 'water_pressure_low'
                          WHEN sensor = 'water_pressure_psi' AND value > 130 THEN 'water_pressure_high'

                          WHEN sensor = 'oil_life_pct' AND value < 10 THEN 'oil_life_critical_low'
                          WHEN sensor = 'oil_life_pct' AND value < 20 THEN 'oil_life_low'

                          WHEN sensor = 'oil_level_pct' AND value < 10 THEN 'oil_level_critical_low'
                          WHEN sensor = 'oil_level_pct' AND value < 20 THEN 'oil_level_low'

                          WHEN sensor = 'drip_oil_level_pct' AND value > 70 THEN 'drip_oil_critical_high'
                          WHEN sensor = 'drip_oil_level_pct' AND value > 40 THEN 'drip_oil_high'

                          WHEN sensor = 'temp_c' AND value > 80 THEN 'temp_critical_high'
                          WHEN sensor = 'temp_c' AND value > 60 THEN 'temp_high'

                          WHEN sensor = 'humidity_pct' AND value > 98 THEN 'humidity_critical_high'
                          WHEN sensor = 'humidity_pct' AND value > 90 THEN 'humidity_high'

                          WHEN sensor = 'vibration_g' AND value > 6 THEN 'vibration_critical_high'
                          WHEN sensor = 'vibration_g' AND value > 4 THEN 'vibration_high'
                          ELSE NULL
                        END AS alert_type
                      FROM latest l
                    )
                    SELECT
                      s.*,
                      CASE
                        WHEN s.severity_num >= 2 THEN 'critical'
                        WHEN s.severity_num = 1 THEN 'warning'
                        ELSE 'ok'
                      END AS severity
                    FROM scored s;
                    """,
                    "marts_edge_telemetry_latest_readings",
                )

                # Active alerts across the fleet (latest per-sensor score > 0).
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_device_alerts")} AS
                    SELECT
                      COALESCE(d.device_id, lr.device_id) AS device_id,
                      d.label,
                      d.revoked_at,
                      lr.sensor,
                      lr.value,
                      lr.units,
                      lr.ts,
                      lr.severity_num,
                      lr.severity,
                      lr.alert_type
                    FROM {_quote_ident("marts_edge_telemetry_latest_readings")} lr
                    LEFT JOIN {_quote_ident("devices")} d
                      ON d.device_id = lr.device_id
                    WHERE lr.severity_num > 0
                    ORDER BY lr.severity_num DESC, lr.ts DESC NULLS LAST;
                    """,
                    "marts_edge_telemetry_device_alerts",
                )

                # Device-level rollup useful for dashboards + offline detection.
                #
                # Field ops note:
                # - We join against the `devices` registry when present so the UI can
                #   show labels, last_seen, and revoked state.
                # - We still surface "unknown" devices that appear in curated telemetry
                #   (e.g., demo seeding) via a LEFT JOIN.
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_device_status")} AS
                    WITH agg AS (
                      SELECT
                        device_id,
                        COUNT(*)::BIGINT AS event_count,
                        MAX(ts) AS last_event_ts,
                        MAX(_loaded_at) AS last_loaded_at
                      FROM {_quote_ident(curated_table)}
                      GROUP BY device_id
                    ),
                    alerts AS (
                      SELECT
                        device_id,
                        COUNT(*)::BIGINT AS alert_count,
                        MAX(severity_num)::INT AS worst_severity_num,
                        ARRAY_REMOVE(ARRAY_AGG(alert_type ORDER BY severity_num DESC, sensor), NULL) AS alerts
                      FROM {_quote_ident("marts_edge_telemetry_latest_readings")}
                      WHERE severity_num > 0
                      GROUP BY device_id
                    )
                    SELECT
                      COALESCE(d.device_id, a.device_id) AS device_id,
                      d.label,
                      d.metadata,
                      d.last_seen_at,
                      d.last_seen_ip,
                      d.last_user_agent,
                      d.revoked_at,
                      COALESCE(a.event_count, 0)::BIGINT AS event_count,
                      a.last_event_ts,
                      a.last_loaded_at,
                      COALESCE(al.alert_count, 0)::BIGINT AS alert_count,
                      CASE COALESCE(al.worst_severity_num, 0)
                        WHEN 2 THEN 'critical'
                        WHEN 1 THEN 'warning'
                        ELSE 'ok'
                      END AS alert_severity,
                      al.alerts,
                      -- Offline heuristic (prefer last_seen if present; fall back to last_event)
                      (
                        COALESCE(d.last_seen_at, a.last_event_ts) IS NULL
                        OR COALESCE(d.last_seen_at, a.last_event_ts) < (NOW() - INTERVAL '{offline_seconds} seconds')
                      ) AS is_offline
                    FROM agg a
                    LEFT JOIN alerts al
                      ON al.device_id = a.device_id
                    LEFT JOIN {_quote_ident("devices")} d
                      ON d.device_id = a.device_id

                    UNION ALL

                    -- Devices that exist in the registry but haven't emitted telemetry yet.
                    SELECT
                      d.device_id,
                      d.label,
                      d.metadata,
                      d.last_seen_at,
                      d.last_seen_ip,
                      d.last_user_agent,
                      d.revoked_at,
                      0::BIGINT AS event_count,
                      NULL::timestamptz AS last_event_ts,
                      NULL::timestamptz AS last_loaded_at,
                      0::BIGINT AS alert_count,
                      'ok'::TEXT AS alert_severity,
                      NULL::TEXT[] AS alerts,
                      (
                        d.last_seen_at IS NULL
                        OR d.last_seen_at < (NOW() - INTERVAL '{offline_seconds} seconds')
                      ) AS is_offline
                    FROM {_quote_ident("devices")} d
                    WHERE NOT EXISTS (SELECT 1 FROM agg a WHERE a.device_id = d.device_id)

                    ORDER BY last_event_ts DESC NULLS LAST;
                    """,
                    "marts_edge_telemetry_device_status",
                )

                # Latest known location per device (from any event that included lat/lon).
                # This is intentionally a separate mart so field ops can render a "fleet map"
                # without scanning the full event stream.
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_device_geo")} AS
                    SELECT DISTINCT ON (device_id)
                      device_id,
                      ts AS last_geo_ts,
                      lat,
                      lon,
                      _loaded_at,
                      _ingestion_id
                    FROM {_quote_ident(curated_table)}
                    WHERE lat IS NOT NULL AND lon IS NOT NULL
                    ORDER BY device_id, ts DESC NULLS LAST, _loaded_at DESC;
                    """,
                    "marts_edge_telemetry_device_geo",
                )

                # Convenience join: device status + last known location.
                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_device_geo_status")} AS
                    SELECT
                      s.*,
                      g.lat,
                      g.lon,
                      g.last_geo_ts
                    FROM {_quote_ident("marts_edge_telemetry_device_status")} s
                    LEFT JOIN {_quote_ident("marts_edge_telemetry_device_geo")} g
                      ON g.device_id = s.device_id;
                    """,
                    "marts_edge_telemetry_device_geo_status",
                )

                _try(
                    cur,
                    f"""
                    CREATE OR REPLACE VIEW {_quote_ident("marts_edge_telemetry_geo_points")} AS
                    SELECT
                      event_id,
                      device_id,
                      ts,
                      sensor,
                      value,
                      units,
                      lat,
                      lon
                    FROM {_quote_ident(curated_table)}
                    WHERE lat IS NOT NULL AND lon IS NOT NULL;
                    """,
                    "marts_edge_telemetry_geo_points",
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

    limit = max(1, min(int(limit), 2000))
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {_quote_ident(view_name)} LIMIT %s;", (limit,))
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

    if dataset == "edge_telemetry":
        marts += [
            {
                "name": "device_status",
                "view": "marts_edge_telemetry_device_status",
                "description": "Device rollup (last seen + offline heuristic)",
            },
            {
                "name": "device_geo_status",
                "view": "marts_edge_telemetry_device_geo_status",
                "description": "Device rollup joined with last known lat/lon (fleet map)",
            },
            {
                "name": "device_alerts",
                "view": "marts_edge_telemetry_device_alerts",
                "description": "Active alerts scored from latest per-sensor readings",
            },
            {
                "name": "latest_readings",
                "view": "marts_edge_telemetry_latest_readings",
                "description": "Latest reading per device + sensor (includes alert severity)",
            },
            {
                "name": "latest_by_device",
                "view": "marts_edge_telemetry_latest_by_device",
                "description": "Latest event per device (handy for debugging)",
            },
            {
                "name": "geo_points",
                "view": "marts_edge_telemetry_geo_points",
                "description": "Lat/Lon points for lightweight mapping in the UI",
            },
        ]

    return marts


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
