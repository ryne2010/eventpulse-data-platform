from __future__ import annotations

import os
import tempfile
import traceback
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from .config import settings
from .contracts import load_contract_with_meta
from .db import (
    get_conn,
    get_ingestion,
    get_latest_schema,
    insert_quality_report,
    insert_audit_event,
    now_utc,
    touch_processing_heartbeat,
    update_ingestion_status,
    upsert_lineage_artifact,
    upsert_schema,
)
from .gcp_rest import gcs_download_file
from .naming import normalize_dataset_name
from .quality import validate_df
from .schema import infer_schema, schema_hash
from .loaders.postgres import upsert_curated


def process_ingestion(ingestion_id: str) -> Dict[str, Any]:
    """Job: validate + drift detect + load curated tables + persist lineage artifact."""

    ingestion = get_ingestion(ingestion_id)
    if not ingestion:
        return {"ok": False, "error": "ingestion_not_found"}

    dataset = normalize_dataset_name(str(ingestion["dataset"]))
    raw_path = str(ingestion["raw_path"])
    file_ext = (ingestion.get("file_ext") or "").lower()
    sha = str(ingestion["sha256"])

    # Idempotency / concurrency control:
    # Claim the ingestion if it's pending or retryable.
    claim = _try_mark_processing(ingestion_id)
    if claim != "claimed":
        if claim == "max_attempts":
            return {"ok": False, "error": "max_processing_attempts_exceeded"}
        return {"ok": True, "skipped": True, "reason": "already_processed_or_in_progress"}

    tmp_path: Optional[str] = None

    try:
        _touch(ingestion_id)

        _audit(
            "ingestion.processing_started",
            dataset=dataset,
            ingestion_id=ingestion_id,
            details={"raw_path": raw_path, "sha256": sha, "file_ext": file_ext},
        )

        contract_meta = load_contract_with_meta(dataset)
        contract = contract_meta.contract
        _touch(ingestion_id)

        local_path, tmp_path = _materialize_raw_to_local(raw_path)
        _touch(ingestion_id)

        df = _load_file(local_path, file_ext)
        _touch(ingestion_id)

        # Infer schema + drift
        observed_schema = infer_schema(df)
        observed_hash = schema_hash(observed_schema)

        previous = get_latest_schema(dataset)
        previous_schema = previous["schema_json"] if previous else None

        drift = _compute_drift(previous_schema, observed_schema)
        drift_policy = (contract.drift_policy or settings.drift_policy_default).lower()

        upsert_schema(dataset, observed_hash, observed_schema)
        _touch(ingestion_id)

        # Quality validation (may mutate df types)
        quality = validate_df(df, contract)
        _touch(ingestion_id)

        report: Dict[str, Any] = {
            "dataset": dataset,
            "source": ingestion.get("source"),
            "raw_path": raw_path,
            "sha256": sha,
            "contract": {
                "path": contract_meta.path,
                "sha256": contract_meta.sha256,
            },
            "observed_schema_hash": observed_hash,
            "drift": drift,
            "drift_policy": drift_policy,
            "quality": {
                "passed": quality.passed,
                "errors": quality.errors,
                "warnings": quality.warnings,
                "metrics": quality.metrics,
            },
        }

        # Drift gating
        drift_is_breaking = drift.get("breaking", False)
        if drift_is_breaking and drift_policy == "fail":
            insert_quality_report(ingestion_id, False, report)
            update_ingestion_status(ingestion_id, "FAILED_DRIFT", error="Schema drift policy=fail")
            _audit(
                "ingestion.failed_drift",
                dataset=dataset,
                ingestion_id=ingestion_id,
                details={"policy": drift_policy, "drift": drift, "observed_schema_hash": observed_hash},
            )
            _persist_lineage_artifact(ingestion_id, report, load_info=None)
            return {"ok": False, "error": "failed_drift", "report": report}

        if not quality.passed:
            insert_quality_report(ingestion_id, False, report)
            update_ingestion_status(ingestion_id, "FAILED_QUALITY", error="Quality gate failed")
            _audit(
                "ingestion.failed_quality",
                dataset=dataset,
                ingestion_id=ingestion_id,
                details={
                    "errors": (quality.errors or [])[:20],
                    "warnings": (quality.warnings or [])[:20],
                    "metrics": quality.metrics,
                },
            )
            _persist_lineage_artifact(ingestion_id, report, load_info=None)
            return {"ok": False, "error": "failed_quality", "report": report}

        # Load curated
        if settings.curated_backend != "postgres":
            raise RuntimeError(
                "Only CURATED_BACKEND=postgres is implemented in this reference repo. "
                "(BigQuery loading is intentionally left as an extension.)"
            )

        rows_loaded = upsert_curated(contract, df, ingestion_id=ingestion_id, source_sha256=sha)
        load_info = {"backend": "postgres", "rows_loaded": rows_loaded, "table": f"curated_{dataset}"}
        report["load"] = load_info
        _touch(ingestion_id)

        insert_quality_report(ingestion_id, True, report)
        update_ingestion_status(ingestion_id, "LOADED")
        _audit(
            "ingestion.loaded",
            dataset=dataset,
            ingestion_id=ingestion_id,
            details={
                "rows_loaded": rows_loaded,
                "table": load_info.get("table"),
                "observed_schema_hash": observed_hash,
            },
        )

        _persist_lineage_artifact(ingestion_id, report, load_info=load_info)

        return {"ok": True, "rows_loaded": rows_loaded, "report": report}

    except Exception as e:
        tb = traceback.format_exc()
        update_ingestion_status(ingestion_id, "FAILED_EXCEPTION", error=str(e))
        _audit(
            "ingestion.failed_exception",
            dataset=dataset,
            ingestion_id=ingestion_id,
            details={"exception": str(e)},
        )
        try:
            insert_quality_report(
                ingestion_id,
                False,
                {
                    "dataset": dataset,
                    "raw_path": raw_path,
                    "sha256": sha,
                    "exception": str(e),
                    "traceback": tb,
                },
            )
        except Exception:
            pass

        try:
            _persist_lineage_artifact(
                ingestion_id,
                {
                    "dataset": dataset,
                    "raw_path": raw_path,
                    "sha256": sha,
                    "exception": str(e),
                    "traceback": tb,
                },
                load_info=None,
            )
        except Exception:
            pass

        return {"ok": False, "error": "exception", "exception": str(e), "traceback": tb}

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _audit(event_type: str, *, dataset: str, ingestion_id: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Best-effort audit logging from the worker."""

    try:
        insert_audit_event(
            event_type=event_type,
            actor="worker",
            dataset=dataset,
            ingestion_id=ingestion_id,
            details=details or {},
        )
    except Exception:
        # Never block ingestion processing on audit logging.
        pass


def _touch(ingestion_id: str) -> None:
    """Best-effort heartbeat update."""

    try:
        touch_processing_heartbeat(ingestion_id)
    except Exception:
        # Heartbeats are a resilience feature; ingestion should still complete.
        pass


def _try_mark_processing(ingestion_id: str) -> str:
    """Atomically claim an ingestion for processing.

    Returns:
      - "claimed": this worker should process the ingestion
      - "skip": another worker already claimed it or it is not retryable
      - "max_attempts": attempts exceeded; ingestion marked terminal

    Retry policy:
    - allow re-processing for FAILED_EXCEPTION (transient failures)
    - do not auto-retry drift/quality failures (business rule)
    """

    max_attempts = max(1, int(settings.max_processing_attempts))

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestions
                SET status='PROCESSING',
                    error=NULL,
                    processed_at=NULL,
                    processing_started_at=%s,
                    processing_heartbeat_at=%s,
                    processing_attempts=processing_attempts + 1
                WHERE id=%s
                  AND status IN ('RECEIVED', 'FAILED_EXCEPTION')
                  AND processing_attempts < %s
                RETURNING id;
                """,
                (now_utc(), now_utc(), ingestion_id, max_attempts),
            )
            row = cur.fetchone()
            if row is not None:
                return "claimed"

            # Safety valve: if attempts are exhausted, mark the ingestion terminal.
            cur.execute(
                """
                UPDATE ingestions
                SET status='FAILED_MAX_ATTEMPTS',
                    error=%s,
                    processed_at=%s,
                    processing_started_at=NULL,
                    processing_heartbeat_at=NULL
                WHERE id=%s
                  AND status IN ('RECEIVED', 'FAILED_EXCEPTION')
                  AND processing_attempts >= %s
                RETURNING id;
                """,
                ("max_processing_attempts_exceeded", now_utc(), ingestion_id, max_attempts),
            )
            row2 = cur.fetchone()
            if row2 is not None:
                return "max_attempts"

            return "skip"


def _materialize_raw_to_local(raw_path: str) -> Tuple[str, Optional[str]]:
    """Return a local filesystem path for a raw artifact.

    - local backend: raw_path is already a local path
    - gcs backend: download to a temp file and return (temp_path, temp_path)
    """

    if raw_path.startswith("gs://"):
        bucket, object_name = _parse_gs_uri(raw_path)
        fd, tmp = tempfile.mkstemp(prefix="eventpulse_raw_", suffix=os.path.splitext(object_name)[1] or ".bin")
        os.close(fd)
        gcs_download_file(bucket, object_name, tmp)
        return tmp, tmp

    return raw_path, None


def _parse_gs_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri}")
    rest = uri[len("gs://") :]
    if "/" not in rest:
        raise ValueError(f"Invalid gs:// URI (missing object): {uri}")
    bucket, object_name = rest.split("/", 1)
    if not bucket or not object_name:
        raise ValueError(f"Invalid gs:// URI: {uri}")
    return bucket, object_name


def _load_file(path: str, ext: str) -> pd.DataFrame:
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type: {ext}")


def _compute_drift(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> Dict[str, Any]:
    if not previous:
        return {"type": "initial", "breaking": False, "details": "first schema observed"}

    prev_cols = {c["name"]: c.get("logical_type") for c in previous.get("columns", [])}
    cur_cols = {c["name"]: c.get("logical_type") for c in current.get("columns", [])}

    added = sorted([c for c in cur_cols.keys() if c not in prev_cols])
    removed = sorted([c for c in prev_cols.keys() if c not in cur_cols])
    changed = sorted([c for c in cur_cols.keys() if c in prev_cols and cur_cols[c] != prev_cols[c]])

    breaking = bool(removed or changed)  # conservative
    return {
        "type": "drift" if (added or removed or changed) else "none",
        "breaking": breaking,
        "added": added,
        "removed": removed,
        "changed_type": {c: {"from": prev_cols[c], "to": cur_cols[c]} for c in changed},
    }


def _persist_lineage_artifact(ingestion_id: str, report: Dict[str, Any], load_info: Optional[Dict[str, Any]]) -> None:
    """Store a governance-friendly lineage artifact per ingestion."""

    dataset = report.get("dataset")

    published_endpoints = [
        "/api/meta",
        "/api/ingestions",
        f"/api/ingestions/{ingestion_id}",
        f"/api/ingestions/{ingestion_id}/preview",
    ]
    if dataset:
        published_endpoints.append(f"/api/datasets/{dataset}/curated/sample")
        published_endpoints.append(f"/api/datasets/{dataset}/schemas")

    artifact = {
        "ingestion_id": ingestion_id,
        "dataset": dataset,
        "raw": {
            "path": report.get("raw_path"),
            "sha256": report.get("sha256"),
        },
        "contract": report.get("contract"),
        "observed_schema_hash": report.get("observed_schema_hash"),
        "drift": report.get("drift"),
        "quality": report.get("quality"),
        "load": load_info,
        "published_endpoints": published_endpoints,
    }

    upsert_lineage_artifact(ingestion_id, artifact)
