import contextlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

from .config import settings
from .device_auth import DEFAULT_PBKDF2_ITERATIONS, generate_device_token, hash_device_token, verify_device_token

logger = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@contextlib.contextmanager
def get_conn(*, connect_timeout: int = 5):
    """Open a new DB connection.

    We intentionally keep this simple (one connection per operation).
    For higher throughput, consider adding a small connection pool.
    """

    conn = psycopg2.connect(settings.database_url, connect_timeout=connect_timeout)
    try:
        yield conn
    finally:
        conn.close()


# -----------------------------
# Migrations (minimal, dependency-free)
# -----------------------------


def _migrations() -> List[Tuple[int, str, str]]:
    """Ordered SQL migrations.

    We keep migrations as code (instead of Alembic) to avoid extra dependencies.
    This still provides:
    - version tracking
    - idempotent schema upgrades
    - deterministic startup behavior

    NOTE: Use PostgreSQL syntax (Cloud SQL / local Docker Postgres).
    """

    return [
        (
            1,
            "init_core_tables",
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ingestions (
              id UUID PRIMARY KEY,
              dataset TEXT NOT NULL,
              source TEXT,
              filename TEXT,
              file_ext TEXT,
              sha256 TEXT NOT NULL,
              raw_path TEXT NOT NULL,
              received_at TIMESTAMPTZ NOT NULL,
              status TEXT NOT NULL,
              error TEXT,
              processed_at TIMESTAMPTZ,
              replay_of UUID NULL
            );

            -- Upgrades from earlier schema versions
            ALTER TABLE ingestions ADD COLUMN IF NOT EXISTS replay_of UUID NULL;

            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM   pg_constraint
                WHERE  conname = 'fk_ingestions_replay_of'
              ) THEN
                ALTER TABLE ingestions
                  ADD CONSTRAINT fk_ingestions_replay_of
                  FOREIGN KEY (replay_of)
                  REFERENCES ingestions(id)
                  ON DELETE SET NULL;
              END IF;
            END $$;

            CREATE INDEX IF NOT EXISTS idx_ingestions_dataset_received_at
              ON ingestions(dataset, received_at DESC);

            CREATE INDEX IF NOT EXISTS idx_ingestions_received_at
              ON ingestions(received_at DESC);

            CREATE TABLE IF NOT EXISTS dataset_schemas (
              dataset TEXT NOT NULL,
              schema_hash TEXT NOT NULL,
              schema_json JSONB NOT NULL,
              first_seen_at TIMESTAMPTZ NOT NULL,
              last_seen_at TIMESTAMPTZ NOT NULL,
              PRIMARY KEY (dataset, schema_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_dataset_schemas_dataset_last_seen
              ON dataset_schemas(dataset, last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS quality_reports (
              ingestion_id UUID PRIMARY KEY REFERENCES ingestions(id) ON DELETE CASCADE,
              passed BOOLEAN NOT NULL,
              report JSONB NOT NULL,
              created_at TIMESTAMPTZ NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lineage_artifacts (
              ingestion_id UUID PRIMARY KEY REFERENCES ingestions(id) ON DELETE CASCADE,
              artifact JSONB NOT NULL,
              created_at TIMESTAMPTZ NOT NULL
            );
            """,
        ),
        (
            2,
            "add_ingestion_status_check_constraint",
            """
            -- Keep status values flexible but prevent obvious empty strings.
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_ingestions_status_not_empty'
              ) THEN
                ALTER TABLE ingestions
                  ADD CONSTRAINT chk_ingestions_status_not_empty
                  CHECK (char_length(status) > 0);
              END IF;
            END $$;
            """,
        ),
        (
            3,
            "add_processing_tracking_columns",
            """
            ALTER TABLE ingestions
              ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ NULL,
              ADD COLUMN IF NOT EXISTS processing_heartbeat_at TIMESTAMPTZ NULL,
              ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0;

            CREATE INDEX IF NOT EXISTS idx_ingestions_status_processing_started_at
              ON ingestions(status, processing_started_at);
            """,
        ),
        (
            4,
            "add_raw_object_generation_and_idempotency",
            """
            ALTER TABLE ingestions
              ADD COLUMN IF NOT EXISTS raw_generation BIGINT NULL;

            -- Idempotency for GCS object finalize events (best-effort).
            -- The (raw_path, raw_generation) pair is stable and dedupes duplicate
            -- deliveries while still allowing manual replays (replay_of != NULL).
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestions_raw_path_generation_unique
              ON ingestions(raw_path, raw_generation)
              WHERE raw_generation IS NOT NULL AND replay_of IS NULL;

            CREATE INDEX IF NOT EXISTS idx_ingestions_raw_path
              ON ingestions(raw_path);
            """,
        ),
        (
            5,
            "add_audit_events",
            """
            CREATE TABLE IF NOT EXISTS audit_events (
              id UUID PRIMARY KEY,
              event_type TEXT NOT NULL,
              actor TEXT,
              dataset TEXT,
              ingestion_id UUID NULL REFERENCES ingestions(id) ON DELETE SET NULL,
              details JSONB,
              created_at TIMESTAMPTZ NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
              ON audit_events(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_audit_events_dataset_created_at
              ON audit_events(dataset, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_audit_events_ingestion_created_at
              ON audit_events(ingestion_id, created_at DESC);

            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_audit_events_type_not_empty'
              ) THEN
                ALTER TABLE audit_events
                  ADD CONSTRAINT chk_audit_events_type_not_empty
                  CHECK (char_length(event_type) > 0);
              END IF;
            END $$;
            """,
        ),
        (
            6,
            "add_devices",
            """
            CREATE TABLE IF NOT EXISTS devices (
              device_id TEXT PRIMARY KEY,
              label TEXT,
              metadata JSONB,
              token_salt TEXT NOT NULL,
              token_hash TEXT NOT NULL,
              token_iterations INTEGER NOT NULL,
              token_updated_at TIMESTAMPTZ NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL,
              revoked_at TIMESTAMPTZ NULL,
              last_seen_at TIMESTAMPTZ NULL,
              last_seen_ip TEXT,
              last_user_agent TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_devices_last_seen_at
              ON devices(last_seen_at DESC);

            CREATE INDEX IF NOT EXISTS idx_devices_revoked_at
              ON devices(revoked_at);

            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_devices_device_id_not_empty'
              ) THEN
                ALTER TABLE devices
                  ADD CONSTRAINT chk_devices_device_id_not_empty
                  CHECK (char_length(device_id) > 0);
              END IF;
            END $$;
            """,
        ),
        (
            7,
            "add_device_media",
            """
            CREATE TABLE IF NOT EXISTS device_media (
              id UUID PRIMARY KEY,
              device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
              media_type TEXT NOT NULL,
              gcs_bucket TEXT NOT NULL,
              object_name TEXT NOT NULL,
              gcs_uri TEXT NOT NULL,
              content_type TEXT,
              bytes BIGINT,
              captured_at TIMESTAMPTZ NULL,
              notes TEXT,
              created_at TIMESTAMPTZ NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_device_media_object_unique
              ON device_media(gcs_bucket, object_name);

            CREATE INDEX IF NOT EXISTS idx_device_media_device_created_at
              ON device_media(device_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_device_media_created_at
              ON device_media(created_at DESC);

            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_device_media_type_not_empty'
              ) THEN
                ALTER TABLE device_media
                  ADD CONSTRAINT chk_device_media_type_not_empty
                  CHECK (char_length(media_type) > 0);
              END IF;
            END $$;
            """,
        ),
    ]


def migrate_db() -> None:
    """Apply any pending migrations.

    Safe to run concurrently across multiple app instances:
    we take a PostgreSQL advisory lock.
    """

    # Arbitrary stable lock ID for this repo.
    lock_id = 43819231

    with get_conn(connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Ensure migrations table exists before trying to lock.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  applied_at TIMESTAMPTZ NOT NULL
                );
                """
            )
            cur.execute("SELECT pg_advisory_lock(%s);", (lock_id,))

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM schema_migrations;")
                applied = {int(r[0]) for r in cur.fetchall()}

                for version, name, sql in _migrations():
                    if version in applied:
                        continue
                    logger.info("Applying DB migration", extra={"migration": name, "version": version})
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (%s, %s, %s);",
                        (version, name, now_utc()),
                    )

        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (lock_id,))


def init_db() -> None:
    """Initialize database schema.

    In local dev (Docker Compose), Postgres and/or DNS can be briefly unavailable
    while the stack is coming up. Retry to avoid flaky startup failures.
    """

    max_wait_seconds = 30.0
    deadline = time.monotonic() + max_wait_seconds
    attempt = 0

    while True:
        attempt += 1
        try:
            migrate_db()
            return
        except psycopg2.OperationalError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            sleep_seconds = min(0.25 * (2 ** (attempt - 1)), 3.0, remaining)
            logger.warning("Database not ready yet (attempt %s): %s", attempt, exc)
            time.sleep(sleep_seconds)


def db_ping() -> bool:
    try:
        with get_conn(connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception:
        return False


# -----------------------------
# Ingestions
# -----------------------------


def insert_ingestion(
    dataset: str,
    source: Optional[str],
    filename: str,
    file_ext: str,
    sha256: str,
    raw_path: str,
    *,
    raw_generation: Optional[int] = None,
    replay_of: Optional[str] = None,
) -> uuid.UUID:
    ingestion_id = uuid.uuid4()
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestions (id, dataset, source, filename, file_ext, sha256, raw_path, raw_generation, received_at, status, replay_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'RECEIVED', %s)
                """,
                (
                    str(ingestion_id),
                    dataset,
                    source,
                    filename,
                    file_ext,
                    sha256,
                    raw_path,
                    raw_generation,
                    now_utc(),
                    replay_of,
                ),
            )
    return ingestion_id


def insert_ingestion_from_gcs_event(
    *,
    dataset: str,
    source: Optional[str],
    filename: str,
    file_ext: str,
    sha256: str,
    raw_path: str,
    raw_generation: int,
) -> tuple[uuid.UUID, bool]:
    """Insert an ingestion record from a GCS object finalize event.

    Event delivery is at-least-once. We dedupe using the stable
    (raw_path, raw_generation) pair.

    Returns:
      (ingestion_id, created)
    """

    ingestion_id = uuid.uuid4()
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestions (id, dataset, source, filename, file_ext, sha256, raw_path, raw_generation, received_at, status, replay_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'RECEIVED', NULL)
                ON CONFLICT (raw_path, raw_generation)
                  WHERE raw_generation IS NOT NULL AND replay_of IS NULL
                DO NOTHING
                RETURNING id;
                """,
                (
                    str(ingestion_id),
                    dataset,
                    source,
                    filename,
                    file_ext,
                    sha256,
                    raw_path,
                    int(raw_generation),
                    now_utc(),
                ),
            )
            row = cur.fetchone()
            if row:
                return uuid.UUID(str(row[0])), True

            # Conflict: find existing ingestion.
            cur.execute(
                """
                SELECT id
                FROM ingestions
                WHERE raw_path=%s AND raw_generation=%s AND replay_of IS NULL
                LIMIT 1;
                """,
                (raw_path, int(raw_generation)),
            )
            existing = cur.fetchone()
            if not existing:
                raise RuntimeError("insert conflict but no existing ingestion found")
            return uuid.UUID(str(existing[0])), False


def create_replay_ingestion(original_ingestion_id: str) -> uuid.UUID:
    orig = get_ingestion(original_ingestion_id)
    if not orig:
        raise ValueError("original ingestion not found")

    source = orig.get("source") or ""
    replay_source = f"replay:{original_ingestion_id}"
    if source:
        replay_source = f"{source};{replay_source}"

    rg = orig.get("raw_generation")
    raw_generation = int(rg) if rg is not None else None

    return insert_ingestion(
        dataset=str(orig["dataset"]),
        source=replay_source,
        filename=str(orig.get("filename") or ""),
        file_ext=str(orig.get("file_ext") or ""),
        sha256=str(orig["sha256"]),
        raw_path=str(orig["raw_path"]),
        raw_generation=raw_generation,
        replay_of=original_ingestion_id,
    )


def get_ingestion(ingestion_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.*, q.passed AS quality_passed
                FROM ingestions i
                LEFT JOIN quality_reports q ON q.ingestion_id = i.id
                WHERE i.id=%s
                """,
                (ingestion_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_ingestions(
    limit: int = 50, dataset: Optional[str] = None, status: Optional[str] = None
) -> Sequence[Dict[str, Any]]:
    """List recent ingestions with optional server-side filters.

    `status` accepts either:
    - group values: received|processing|success|failed
    - a raw ingestion status (e.g. FAILED_QUALITY)

    Filtering is intentionally conservative (exact match, safe parameterization).
    """

    limit = max(1, min(int(limit), 500))

    where: List[str] = []
    params: List[Any] = []

    if dataset:
        where.append("i.dataset=%s")
        params.append(str(dataset))

    if status:
        s = str(status).strip().lower()
        if s == "success":
            where.append("i.status='LOADED'")
        elif s == "failed":
            where.append("i.status LIKE 'FAILED%'")
        elif s == "processing":
            where.append("i.status='PROCESSING'")
        elif s == "received":
            where.append("i.status='RECEIVED'")
        else:
            where.append("i.status=%s")
            params.append(str(status).strip().upper())

    sql = """
        SELECT i.*, q.passed AS quality_passed
        FROM ingestions i
        LEFT JOIN quality_reports q ON q.ingestion_id = i.id
    """.strip()
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY i.received_at DESC LIMIT %s"

    params.append(limit)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def update_ingestion_status(ingestion_id: str, status: str, error: Optional[str] = None) -> None:
    """Update ingestion status.

    `processed_at` semantics:
    - PROCESSING: processed_at is cleared (NULL)
    - terminal statuses (LOADED / FAILED_*): processed_at is set to now
    """

    terminal = status not in ("RECEIVED", "PROCESSING")
    processed_at = now_utc() if terminal else None

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestions
                SET status=%s,
                    error=%s,
                    processed_at=%s
                WHERE id=%s
                """,
                (status, error, processed_at, ingestion_id),
            )


def touch_processing_heartbeat(ingestion_id: str) -> None:
    """Update processing heartbeat for an in-flight ingestion.

    This is a lightweight liveness signal used by the stuck-ingestion reclaimer.
    We only touch rows that are currently PROCESSING.
    """

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestions
                SET processing_heartbeat_at=%s
                WHERE id=%s AND status='PROCESSING'
                """,
                (now_utc(), ingestion_id),
            )


def reclaim_stuck_ingestions(*, older_than_seconds: int, limit: int = 50) -> List[str]:
    """Reclaim ingestions stuck in PROCESSING.

    Why this exists:
    - Cloud Tasks (and job queues in general) will retry on transient failures.
    - If a worker dies *after* marking the DB row PROCESSING but *before* finishing,
      retries can be skipped because the ingestion is already "in progress".

    This function marks old PROCESSING rows as FAILED_EXCEPTION so they are
    retryable.

    Returns a list of reclaimed ingestion IDs.
    """

    limit = max(1, min(int(limit), 500))
    older_than_seconds = max(30, int(older_than_seconds))

    cutoff = now_utc() - timedelta(seconds=older_than_seconds)

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH stuck AS (
                  SELECT id
                  FROM ingestions
                  WHERE status='PROCESSING'
                    AND COALESCE(processing_heartbeat_at, processing_started_at, received_at) < %s
                  ORDER BY COALESCE(processing_heartbeat_at, processing_started_at, received_at) ASC
                  LIMIT %s
                )
                UPDATE ingestions i
                SET status='FAILED_EXCEPTION',
                    error='reclaimed_stuck_processing',
                    processed_at=%s
                FROM stuck
                WHERE i.id = stuck.id
                RETURNING i.id;
                """,
                (cutoff, limit, now_utc()),
            )
            rows = cur.fetchall()

    return [str(r[0]) for r in rows]


# -----------------------------
# Schemas
# -----------------------------


def upsert_schema(dataset: str, schema_hash: str, schema_json: Dict[str, Any]) -> None:
    """Insert schema if new, otherwise update last_seen_at."""

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dataset_schemas (dataset, schema_hash, schema_json, first_seen_at, last_seen_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (dataset, schema_hash)
                DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
                """,
                (dataset, schema_hash, json.dumps(schema_json), now_utc(), now_utc()),
            )


def get_latest_schema(dataset: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT schema_hash, schema_json, first_seen_at, last_seen_at
                FROM dataset_schemas
                WHERE dataset=%s
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (dataset,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "schema_hash": row["schema_hash"],
                "schema_json": row["schema_json"],
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
            }


def list_schema_history(dataset: str, limit: int = 20) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT schema_hash, schema_json, first_seen_at, last_seen_at
                FROM dataset_schemas
                WHERE dataset=%s
                ORDER BY last_seen_at DESC
                LIMIT %s
                """,
                (dataset, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]

    # Normalize datetimes to ISO for API usage.
    for r in rows:
        for k in ("first_seen_at", "last_seen_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return rows


# -----------------------------
# Quality reports
# -----------------------------


def insert_quality_report(ingestion_id: str, passed: bool, report: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quality_reports (ingestion_id, passed, report, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ingestion_id)
                DO UPDATE SET passed=EXCLUDED.passed, report=EXCLUDED.report, created_at=EXCLUDED.created_at
                """,
                (ingestion_id, passed, json.dumps(report), now_utc()),
            )


def get_quality_report(ingestion_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT passed, report, created_at
                FROM quality_reports
                WHERE ingestion_id=%s
                """,
                (ingestion_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "passed": row["passed"],
                "report": row["report"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }


# -----------------------------
# Lineage artifacts
# -----------------------------


def upsert_lineage_artifact(ingestion_id: str, artifact: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO lineage_artifacts (ingestion_id, artifact, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (ingestion_id)
                DO UPDATE SET artifact=EXCLUDED.artifact, created_at=EXCLUDED.created_at
                """,
                (ingestion_id, json.dumps(artifact), now_utc()),
            )


def get_lineage_artifact(ingestion_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT artifact, created_at
                FROM lineage_artifacts
                WHERE ingestion_id=%s
                """,
                (ingestion_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "artifact": row["artifact"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }


# -----------------------------
# Platform stats / UI helpers
# -----------------------------


_STATUS_GROUP_CASE = """
CASE
  WHEN status='RECEIVED' THEN 'received'
  WHEN status='PROCESSING' THEN 'processing'
  WHEN status='LOADED' THEN 'success'
  WHEN status LIKE 'FAILED%' THEN 'failed'
  ELSE lower(status)
END
"""


def list_dataset_summaries(limit: int = 50) -> List[Dict[str, Any]]:
    """Return per-dataset summary stats for UI.

    Includes datasets present in the ingestions table. Contract presence is
    handled at the API layer (contracts live on disk, not in Postgres).
    """

    limit = max(1, min(int(limit), 200))

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  dataset,
                  COUNT(*) AS ingestion_count,
                  MAX(received_at) AS last_received_at,
                  MAX(processed_at) AS last_processed_at,
                  SUM(CASE WHEN status='RECEIVED' THEN 1 ELSE 0 END) AS received_count,
                  SUM(CASE WHEN status='PROCESSING' THEN 1 ELSE 0 END) AS processing_count,
                  SUM(CASE WHEN status='LOADED' THEN 1 ELSE 0 END) AS success_count,
                  SUM(CASE WHEN status LIKE 'FAILED%' THEN 1 ELSE 0 END) AS failed_count
                FROM ingestions
                GROUP BY dataset
                ORDER BY MAX(received_at) DESC NULLS LAST
                LIMIT %s;
                """,
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]

    def _iso(v: Any) -> Optional[str]:
        return v.isoformat() if hasattr(v, "isoformat") and v is not None else None

    for r in rows:
        r["last_received_at"] = _iso(r.get("last_received_at"))
        r["last_processed_at"] = _iso(r.get("last_processed_at"))

    return rows


def get_platform_stats(hours: int = 24) -> Dict[str, Any]:
    """Return lightweight operational stats for the dashboard UI."""

    hours = max(1, min(int(hours), 168))
    since = now_utc() - timedelta(hours=hours)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Totals
            cur.execute(
                f"""
                SELECT {_STATUS_GROUP_CASE} AS status, COUNT(*)::INT AS count
                FROM ingestions
                GROUP BY 1;
                """
            )
            totals = {str(r["status"]): int(r["count"]) for r in cur.fetchall()}

            # Recent
            cur.execute(
                f"""
                SELECT {_STATUS_GROUP_CASE} AS status, COUNT(*)::INT AS count
                FROM ingestions
                WHERE received_at >= %s
                GROUP BY 1;
                """,
                (since,),
            )
            recent = {str(r["status"]): int(r["count"]) for r in cur.fetchall()}

            # Hourly activity (received)
            cur.execute(
                f"""
                SELECT date_trunc('hour', received_at) AS hour, {_STATUS_GROUP_CASE} AS status, COUNT(*)::INT AS count
                FROM ingestions
                WHERE received_at >= %s
                GROUP BY 1,2
                ORDER BY 1 ASC;
                """,
                (since,),
            )
            hourly_rows = [dict(r) for r in cur.fetchall()]

            # Stuck ingestions (based on heartbeat)
            cutoff = now_utc() - timedelta(seconds=int(settings.processing_ttl_seconds))
            cur.execute(
                """
                SELECT COUNT(*)::INT AS count
                FROM ingestions
                WHERE status='PROCESSING'
                  AND COALESCE(processing_heartbeat_at, processing_started_at, received_at) < %s;
                """,
                (cutoff,),
            )
            stuck_count = int((cur.fetchone() or {}).get("count") or 0)

    # Pivot hourly into a stable list for charts.
    by_hour: Dict[str, Dict[str, Any]] = {}
    for r in hourly_rows:
        h = r.get("hour")
        iso = h.isoformat() if isinstance(h, datetime) else str(h)
        d = by_hour.setdefault(
            iso,
            {"hour": iso, "received": 0, "processing": 0, "success": 0, "failed": 0, "other": 0},
        )
        status = str(r.get("status") or "other")
        cnt = int(r.get("count") or 0)
        if status in ("received", "processing", "success", "failed"):
            d[status] += cnt
        else:
            d["other"] += cnt

    activity = [by_hour[k] for k in sorted(by_hour.keys())]

    total = sum(totals.values())
    backlog = int(totals.get("received", 0) + totals.get("processing", 0))
    success = int(totals.get("success", 0))
    failed = int(totals.get("failed", 0))
    success_rate = (success / max(1, (success + failed))) if (success + failed) else None

    return {
        "hours": hours,
        "totals": totals,
        "recent": recent,
        "activity": activity,
        "total_ingestions": total,
        "backlog": backlog,
        "stuck_processing": stuck_count,
        "success_rate": success_rate,
    }


# -----------------------------
# Audit log (governance-friendly)
# -----------------------------


def insert_audit_event(
    *,
    event_type: str,
    actor: Optional[str] = None,
    dataset: Optional[str] = None,
    ingestion_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Insert an audit event.

    This is a lightweight "operational governance" table intended to support:
    - debugging (who/what changed, when)
    - compliance posture (auditable change trail)
    - UI timelines (ingestion lifecycle, contract updates)

    Actor is best-effort:
    - In Cloud Run IAM mode you can pass user email from headers
    - In token mode you can pass a human-friendly label (e.g. 'ui', 'worker', 'scheduler')
    """

    event_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_events (id, event_type, actor, dataset, ingestion_id, details, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    str(event_type),
                    actor,
                    dataset,
                    ingestion_id,
                    json.dumps(details or {}),
                    now_utc(),
                ),
            )
    return event_id


def list_audit_events(
    *,
    limit: int = 200,
    dataset: Optional[str] = None,
    ingestion_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))

    where: List[str] = []
    params: List[Any] = []

    if dataset:
        where.append("dataset=%s")
        params.append(str(dataset))

    if ingestion_id:
        where.append("ingestion_id=%s")
        params.append(str(ingestion_id))

    if event_type:
        where.append("event_type=%s")
        params.append(str(event_type))

    if actor:
        where.append("actor=%s")
        params.append(str(actor))

    sql = "SELECT * FROM audit_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]

    for r in rows:
        ca = r.get("created_at")
        if isinstance(ca, datetime):
            r["created_at"] = ca.isoformat()
    return rows


# -----------------------------
# Maintenance / retention
# -----------------------------


def get_db_stats() -> Dict[str, Any]:
    """Return lightweight database storage stats.

    This is intended for:
    - ops UI widgets
    - detecting runaway table growth
    - basic "is my DB healthy" checks

    We intentionally avoid expensive full table scans; row counts are estimates.
    """

    core_tables = [
        "ingestions",
        "quality_reports",
        "lineage_artifacts",
        "dataset_schemas",
        "audit_events",
        "devices",
    ]

    captured_at = now_utc()

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS name, pg_database_size(current_database()) AS size_bytes")
            db_row = dict(cur.fetchone() or {})

            tables: List[Dict[str, Any]] = []
            for t in core_tables:
                try:
                    cur.execute(
                        "SELECT pg_total_relation_size(%s::regclass) AS size_bytes",
                        (t,),
                    )
                    size_bytes = int((cur.fetchone() or {}).get("size_bytes") or 0)

                    # Approximate row count using planner stats.
                    cur.execute(
                        "SELECT reltuples::BIGINT AS row_estimate FROM pg_class WHERE relname=%s",
                        (t,),
                    )
                    row_est = cur.fetchone()
                    row_estimate = int(row_est.get("row_estimate") or 0) if row_est else 0

                    tables.append({"name": t, "size_bytes": size_bytes, "row_estimate": row_estimate})
                except Exception as e:
                    logger.warning("failed to collect table stats", extra={"table": t, "error": str(e)})
                    tables.append({"name": t, "size_bytes": 0, "row_estimate": 0, "error": str(e)})

    # Sort descending by size for friendly UI display.
    tables.sort(key=lambda r: int(r.get("size_bytes") or 0), reverse=True)

    return {
        "captured_at": captured_at.isoformat(),
        "database": {
            "name": str(db_row.get("name") or ""),
            "size_bytes": int(db_row.get("size_bytes") or 0),
        },
        "tables": tables,
    }


def prune_audit_events(*, older_than_days: int, limit: int = 50_000, dry_run: bool = True) -> Dict[str, Any]:
    """Prune old audit events.

    Deletes oldest-first to reduce index churn and keep runtimes bounded.
    """

    older_than_days = max(1, min(int(older_than_days), 3650))  # cap at ~10 years
    limit = max(1, min(int(limit), 500_000))

    cutoff = now_utc() - timedelta(days=older_than_days)

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*)::BIGINT AS count FROM audit_events WHERE created_at < %s", (cutoff,))
            total_candidates = int((cur.fetchone() or {}).get("count") or 0)

            planned = min(total_candidates, limit)
            deleted = 0

            if not dry_run and planned:
                cur.execute(
                    """
                    WITH del AS (
                      SELECT id
                      FROM audit_events
                      WHERE created_at < %s
                      ORDER BY created_at ASC
                      LIMIT %s
                    )
                    DELETE FROM audit_events a
                    USING del
                    WHERE a.id = del.id
                    RETURNING a.id
                    """,
                    (cutoff, limit),
                )
                deleted = len(cur.fetchall() or [])

    return {
        "dry_run": bool(dry_run),
        "older_than_days": older_than_days,
        "cutoff": cutoff.isoformat(),
        "limit": limit,
        "total_candidates": total_candidates,
        "planned": planned,
        "deleted": deleted,
    }


def prune_ingestions(*, older_than_days: int, limit: int = 5_000, dry_run: bool = True) -> Dict[str, Any]:
    """Prune old terminal ingestions.

    Safety notes:
    - only deletes terminal rows: LOADED and FAILED_*
    - older-than is based on processed_at

    Deleting ingestion rows cascades to quality_reports and lineage_artifacts.
    Audit events referencing the ingestion will have ingestion_id set to NULL.
    """

    older_than_days = max(1, min(int(older_than_days), 3650))
    limit = max(1, min(int(limit), 200_000))

    cutoff = now_utc() - timedelta(days=older_than_days)

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COUNT(*)::BIGINT AS count
                FROM ingestions
                WHERE (status='LOADED' OR status LIKE 'FAILED%')
                  AND processed_at IS NOT NULL
                  AND processed_at < %s
                """,
                (cutoff,),
            )
            total_candidates = int((cur.fetchone() or {}).get("count") or 0)

            planned = min(total_candidates, limit)
            deleted = 0

            if not dry_run and planned:
                cur.execute(
                    """
                    WITH del AS (
                      SELECT id
                      FROM ingestions
                      WHERE (status='LOADED' OR status LIKE 'FAILED%')
                        AND processed_at IS NOT NULL
                        AND processed_at < %s
                      ORDER BY processed_at ASC
                      LIMIT %s
                    )
                    DELETE FROM ingestions i
                    USING del
                    WHERE i.id = del.id
                    RETURNING i.id
                    """,
                    (cutoff, limit),
                )
                deleted = len(cur.fetchall() or [])

    return {
        "dry_run": bool(dry_run),
        "older_than_days": older_than_days,
        "cutoff": cutoff.isoformat(),
        "limit": limit,
        "total_candidates": total_candidates,
        "planned": planned,
        "deleted": deleted,
    }


# -----------------------------
# Trends (quality)
# -----------------------------


def get_quality_trend(
    *,
    dataset: Optional[str] = None,
    hours: int = 168,
    bucket_minutes: int = 60,
) -> Dict[str, Any]:
    """Return quality pass/fail trend buckets."""

    hours = max(1, min(int(hours), 24 * 30))  # cap at 30 days
    bucket_minutes = int(bucket_minutes)
    if bucket_minutes not in (15, 30, 60, 120, 360, 720, 1440):
        raise ValueError("bucket_minutes must be one of 15,30,60,120,360,720,1440")

    bucket_seconds = bucket_minutes * 60
    end = now_utc()
    start = end - timedelta(hours=hours)

    # Align start/end to bucket boundaries (UTC epoch)
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    start_bucket = (start_epoch // bucket_seconds) * bucket_seconds
    end_bucket = (end_epoch // bucket_seconds) * bucket_seconds

    with get_conn() as conn:
        with conn.cursor() as cur:
            where = ["i.received_at >= %s"]
            params: List[Any] = [start]
            if dataset:
                where.append("i.dataset=%s")
                params.append(str(dataset))

            cur.execute(
                f"""
                SELECT
                  (FLOOR(EXTRACT(EPOCH FROM i.received_at) / %s) * %s)::BIGINT AS bucket_epoch,
                  COUNT(*)::INT AS total,
                  SUM(CASE WHEN q.passed THEN 1 ELSE 0 END)::INT AS passed,
                  SUM(CASE WHEN NOT q.passed THEN 1 ELSE 0 END)::INT AS failed,
                  AVG(COALESCE(NULLIF((q.report->'quality'->'metrics'->>'row_count'), '')::INT, 0))::FLOAT AS avg_rows
                FROM ingestions i
                JOIN quality_reports q ON q.ingestion_id = i.id
                WHERE {" AND ".join(where)}
                GROUP BY 1
                ORDER BY 1 ASC;
                """,
                (bucket_seconds, bucket_seconds, *params),
            )
            rows = cur.fetchall()

    by_bucket: Dict[int, Dict[str, Any]] = {}
    for bucket_epoch, total, passed, failed, avg_rows in rows:
        be = int(bucket_epoch)
        by_bucket[be] = {
            "bucket": datetime.fromtimestamp(be, tz=timezone.utc).isoformat(),
            "total": int(total or 0),
            "passed": int(passed or 0),
            "failed": int(failed or 0),
            "avg_rows": float(avg_rows or 0.0),
        }

    buckets: List[Dict[str, Any]] = []
    for be in range(start_bucket, end_bucket + bucket_seconds, bucket_seconds):
        buckets.append(
            by_bucket.get(
                be,
                {
                    "bucket": datetime.fromtimestamp(be, tz=timezone.utc).isoformat(),
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "avg_rows": 0.0,
                },
            )
        )

    return {
        "dataset": dataset,
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "series": buckets,
    }


# -----------------------------
# Devices (edge auth)
# -----------------------------


def create_device(
    *,
    device_id: str,
    label: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str]:
    """Provision a new device with a generated token.

    Returns:
      (device_row, plaintext_token)

    Notes:
    - The plaintext token is only available at create/rotate time.
    - The DB stores only a derived hash + salt.
    """

    device_id = str(device_id or "").strip()
    if not device_id:
        raise ValueError("device_id is required")

    token = generate_device_token()
    th = hash_device_token(token)

    now = now_utc()

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO devices (
                      device_id, label, metadata,
                      token_salt, token_hash, token_iterations, token_updated_at,
                      created_at, updated_at, revoked_at,
                      last_seen_at, last_seen_ip, last_user_agent
                    )
                    VALUES (
                      %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, NULL,
                      NULL, NULL, NULL
                    )
                    RETURNING
                      device_id, label, metadata,
                      token_updated_at, created_at, updated_at,
                      revoked_at, last_seen_at, last_seen_ip, last_user_agent;
                    """,
                    (
                        device_id,
                        label,
                        psycopg2.extras.Json(metadata) if metadata is not None else None,
                        th.salt_b64,
                        th.hash_b64,
                        th.iterations,
                        now,
                        now,
                        now,
                    ),
                )
            except psycopg2.IntegrityError as exc:
                # device_id already exists
                raise ValueError("device already exists") from exc

            row = cur.fetchone()
            return (dict(row) if row else {"device_id": device_id}), token


def enroll_device(
    *,
    device_id: str,
    enroll_fingerprint: str,
    label: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], str, bool]:
    """Enroll (or recover) a field device using an enrollment fingerprint.

    This function is used by the public edge enrollment endpoint.

    Behavior:
    - If the device_id does not exist: create a new device and return a plaintext token.
    - If the device_id exists and is NOT revoked: rotate the token *only if* the provided
      fingerprint matches metadata.enroll_fingerprint.
    - If revoked, or fingerprint mismatches: raise ValueError.

    Returns:
      (device_row, plaintext_token, created)
    """

    device_id = str(device_id or "").strip()
    if not device_id:
        raise ValueError("device_id is required")

    fp = str(enroll_fingerprint or "").strip()
    if not fp:
        raise ValueError("enroll_fingerprint is required")

    token = generate_device_token()
    th = hash_device_token(token)
    now = now_utc()

    md: Dict[str, Any] = {"enroll_fingerprint": fp, "enroll_fingerprint_v": 1}
    if isinstance(metadata, dict):
        # Do not allow callers to override the fingerprint key.
        for k, v in metadata.items():
            if k in ("enroll_fingerprint", "enroll_fingerprint_v"):
                continue
            md[k] = v

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO devices (
                  device_id, label, metadata,
                  token_salt, token_hash, token_iterations, token_updated_at,
                  created_at, updated_at, revoked_at,
                  last_seen_at, last_seen_ip, last_user_agent
                )
                VALUES (
                  %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, NULL,
                  NULL, NULL, NULL
                )
                ON CONFLICT (device_id) DO UPDATE
                SET
                  label = COALESCE(EXCLUDED.label, devices.label),
                  metadata = COALESCE(devices.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                  token_salt = EXCLUDED.token_salt,
                  token_hash = EXCLUDED.token_hash,
                  token_iterations = EXCLUDED.token_iterations,
                  token_updated_at = EXCLUDED.token_updated_at,
                  updated_at = EXCLUDED.updated_at
                WHERE
                  devices.revoked_at IS NULL
                  AND (devices.metadata->>'enroll_fingerprint') = (EXCLUDED.metadata->>'enroll_fingerprint')
                RETURNING
                  device_id, label, metadata,
                  token_updated_at, created_at, updated_at,
                  revoked_at, last_seen_at, last_seen_ip, last_user_agent,
                  (xmax = 0) AS created;
                """,
                (
                    device_id,
                    label,
                    psycopg2.extras.Json(md),
                    th.salt_b64,
                    th.hash_b64,
                    th.iterations,
                    now,
                    now,
                    now,
                ),
            )

            row = cur.fetchone()
            if not row:
                # Conflict where clause prevented update OR device revoked.
                # Determine which for better error messaging.
                cur.execute(
                    """
                    SELECT revoked_at, metadata
                    FROM devices
                    WHERE device_id=%s
                    LIMIT 1;
                    """,
                    (device_id,),
                )
                existing = cur.fetchone()
                if not existing:
                    raise ValueError("device enroll failed")
                if existing.get("revoked_at") is not None:
                    raise ValueError("device is revoked")
                raise ValueError("enroll fingerprint mismatch")

            created = bool(row.get("created"))
            row.pop("created", None)
            return (dict(row), token, created)


def rotate_device_token(device_id: str) -> str:
    """Rotate a device token (revokes the old one)."""

    device_id = str(device_id or "").strip()
    if not device_id:
        raise ValueError("device_id is required")

    token = generate_device_token()
    th = hash_device_token(token)
    now = now_utc()

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE devices
                SET token_salt=%s,
                    token_hash=%s,
                    token_iterations=%s,
                    token_updated_at=%s,
                    updated_at=%s
                WHERE device_id=%s AND revoked_at IS NULL
                """,
                (th.salt_b64, th.hash_b64, th.iterations, now, now, device_id),
            )
            if cur.rowcount != 1:
                raise ValueError("device not found or revoked")

    return token


def revoke_device(device_id: str) -> bool:
    """Revoke a device (disables token auth)."""

    device_id = str(device_id or "").strip()
    if not device_id:
        raise ValueError("device_id is required")

    now = now_utc()
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE devices
                SET revoked_at=%s, updated_at=%s
                WHERE device_id=%s AND revoked_at IS NULL
                """,
                (now, now, device_id),
            )
            return cur.rowcount == 1


def list_devices(limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  device_id,
                  label,
                  metadata,
                  token_updated_at,
                  token_iterations,
                  created_at,
                  updated_at,
                  revoked_at,
                  last_seen_at,
                  last_seen_ip,
                  last_user_agent
                FROM devices
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    device_id = str(device_id or "").strip()
    if not device_id:
        return None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  device_id,
                  label,
                  metadata,
                  token_updated_at,
                  token_iterations,
                  created_at,
                  updated_at,
                  revoked_at,
                  last_seen_at,
                  last_seen_ip,
                  last_user_agent
                FROM devices
                WHERE device_id=%s
                LIMIT 1;
                """,
                (device_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None




# -----------------------------
# Device media (optional)
# -----------------------------


def create_device_media(
    *,
    device_id: str,
    media_type: str,
    gcs_bucket: str,
    object_name: str,
    gcs_uri: str,
    content_type: Optional[str] = None,
    bytes: Optional[int] = None,
    captured_at: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a device media record.

    Media is uploaded out-of-band (direct-to-GCS). This table tracks references
    and supports a simple UI for field ops.
    """

    device_id = str(device_id or '').strip()
    if not device_id:
        raise ValueError('device_id is required')

    media_type = str(media_type or '').strip().lower()
    if not media_type:
        raise ValueError('media_type is required')

    gcs_bucket = str(gcs_bucket or '').strip()
    object_name = str(object_name or '').strip()
    gcs_uri = str(gcs_uri or '').strip()
    if not gcs_bucket or not object_name or not gcs_uri:
        raise ValueError('gcs_bucket/object_name/gcs_uri are required')

    mid = uuid.uuid4()
    now = now_utc()

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO device_media (
                  id, device_id, media_type, gcs_bucket, object_name, gcs_uri,
                  content_type, bytes, captured_at, notes, created_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING
                  id, device_id, media_type, gcs_bucket, object_name, gcs_uri,
                  content_type, bytes, captured_at, notes, created_at;
                """,
                (
                    mid,
                    device_id,
                    media_type,
                    gcs_bucket,
                    object_name,
                    gcs_uri,
                    (str(content_type).strip()[:200] if content_type else None),
                    int(bytes) if bytes is not None else None,
                    captured_at,
                    (str(notes).strip()[:1000] if notes else None),
                    now,
                ),
            )
            row = cur.fetchone()
            return dict(row) if row else {
                'id': str(mid),
                'device_id': device_id,
                'media_type': media_type,
                'gcs_bucket': gcs_bucket,
                'object_name': object_name,
                'gcs_uri': gcs_uri,
                'content_type': content_type,
                'bytes': bytes,
                'captured_at': captured_at,
                'notes': notes,
                'created_at': now,
            }


def list_device_media(*, limit: int = 200, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    device_id = str(device_id or '').strip() if device_id is not None else None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if device_id:
                cur.execute(
                    """
                    SELECT
                      id, device_id, media_type, gcs_bucket, object_name, gcs_uri,
                      content_type, bytes, captured_at, notes, created_at
                    FROM device_media
                    WHERE device_id=%s
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (device_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                      id, device_id, media_type, gcs_bucket, object_name, gcs_uri,
                      content_type, bytes, captured_at, notes, created_at
                    FROM device_media
                    ORDER BY created_at DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]


def get_device_media(media_id: str) -> Optional[Dict[str, Any]]:
    media_id = str(media_id or '').strip()
    if not media_id:
        return None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  id, device_id, media_type, gcs_bucket, object_name, gcs_uri,
                  content_type, bytes, captured_at, notes, created_at
                FROM device_media
                WHERE id=%s
                LIMIT 1;
                """,
                (media_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
def verify_device_credentials(
    *,
    device_id: str,
    token: str,
    last_seen_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """Validate device credentials and update last_seen fields on success."""

    device_id = str(device_id or "").strip()
    if not device_id:
        return False

    token = str(token or "").strip()
    if not token:
        return False

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT token_salt, token_hash, token_iterations, revoked_at
                FROM devices
                WHERE device_id=%s
                LIMIT 1;
                """,
                (device_id,),
            )
            row = cur.fetchone()
            if not row:
                return False
            if row.get("revoked_at") is not None:
                return False

            salt_b64 = str(row.get("token_salt") or "")
            hash_b64 = str(row.get("token_hash") or "")
            try:
                iterations = int(row.get("token_iterations") or DEFAULT_PBKDF2_ITERATIONS)
            except Exception:
                iterations = DEFAULT_PBKDF2_ITERATIONS
            if not verify_device_token(token, salt_b64=salt_b64, hash_b64=hash_b64, iterations=iterations):
                return False

            now = now_utc()
            cur.execute(
                """
                UPDATE devices
                SET last_seen_at=%s,
                    last_seen_ip=%s,
                    last_user_agent=%s,
                    updated_at=%s
                WHERE device_id=%s;
                """,
                (now, last_seen_ip, user_agent, now, device_id),
            )
            return True
