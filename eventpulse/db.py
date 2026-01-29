import contextlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

from .config import settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@contextlib.contextmanager
def get_conn():
    conn = psycopg2.connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create core tables if they don't exist."""
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
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
                    processed_at TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS dataset_schemas (
                    dataset TEXT NOT NULL,
                    schema_hash TEXT NOT NULL,
                    schema_json JSONB NOT NULL,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (dataset, schema_hash)
                );

                CREATE TABLE IF NOT EXISTS quality_reports (
                    ingestion_id UUID PRIMARY KEY REFERENCES ingestions(id) ON DELETE CASCADE,
                    passed BOOLEAN NOT NULL,
                    report JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                """
            )


def insert_ingestion(
    dataset: str,
    source: Optional[str],
    filename: str,
    file_ext: str,
    sha256: str,
    raw_path: str,
) -> uuid.UUID:
    ingestion_id = uuid.uuid4()
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestions (id, dataset, source, filename, file_ext, sha256, raw_path, received_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'RECEIVED')
                """,
                (str(ingestion_id), dataset, source, filename, file_ext, sha256, raw_path, now_utc()),
            )
    return ingestion_id


def get_ingestion(ingestion_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM ingestions WHERE id=%s", (ingestion_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def list_ingestions(limit: int = 50) -> Sequence[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM ingestions
                ORDER BY received_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def update_ingestion_status(ingestion_id: str, status: str, error: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestions
                SET status=%s, error=%s, processed_at=%s
                WHERE id=%s
                """,
                (status, error, now_utc(), ingestion_id),
            )


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
                SELECT schema_json
                FROM dataset_schemas
                WHERE dataset=%s
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (dataset,),
            )
            row = cur.fetchone()
            return dict(row["schema_json"]) if row else None


def insert_quality_report(ingestion_id: str, passed: bool, report: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quality_reports (ingestion_id, passed, report, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ingestion_id) DO UPDATE SET passed=EXCLUDED.passed, report=EXCLUDED.report, created_at=EXCLUDED.created_at
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
