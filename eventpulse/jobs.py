from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Optional

import pandas as pd

from .config import settings
from .contracts import load_contract
from .db import (
    get_ingestion,
    get_latest_schema,
    insert_quality_report,
    update_ingestion_status,
    upsert_schema,
)
from .quality import validate_df
from .schema import infer_schema, schema_hash
from .loaders.postgres import upsert_curated


def process_ingestion(ingestion_id: str) -> Dict[str, Any]:
    """RQ job: validate + drift detect + load curated tables."""
    ingestion = get_ingestion(ingestion_id)
    if not ingestion:
        return {"ok": False, "error": "ingestion_not_found"}

    dataset = ingestion["dataset"]
    raw_path = ingestion["raw_path"]
    file_ext = (ingestion.get("file_ext") or "").lower()
    sha = ingestion["sha256"]

    try:
        update_ingestion_status(ingestion_id, "PROCESSING")

        contract = load_contract(dataset)

        df = _load_file(raw_path, file_ext)

        # Infer schema + drift
        observed_schema = infer_schema(df)
        observed_hash = schema_hash(observed_schema)
        previous_schema = get_latest_schema(dataset)

        drift = _compute_drift(previous_schema, observed_schema)
        drift_policy = (contract.drift_policy or settings.drift_policy_default).lower()

        upsert_schema(dataset, observed_hash, observed_schema)

        # Quality validation (may mutate df types)
        quality = validate_df(df, contract)

        report: Dict[str, Any] = {
            "dataset": dataset,
            "source": ingestion.get("source"),
            "raw_path": raw_path,
            "sha256": sha,
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
            return {"ok": False, "error": "failed_drift", "report": report}

        if not quality.passed:
            insert_quality_report(ingestion_id, False, report)
            update_ingestion_status(ingestion_id, "FAILED_QUALITY", error="Quality gate failed")
            return {"ok": False, "error": "failed_quality", "report": report}

        # Load curated
        rows_loaded = upsert_curated(contract, df, ingestion_id=ingestion_id, source_sha256=sha)
        report["load"] = {"rows_loaded": rows_loaded}

        insert_quality_report(ingestion_id, True, report)
        update_ingestion_status(ingestion_id, "LOADED")
        return {"ok": True, "rows_loaded": rows_loaded, "report": report}

    except Exception as e:
        tb = traceback.format_exc()
        update_ingestion_status(ingestion_id, "FAILED_EXCEPTION", error=str(e))
        try:
            insert_quality_report(
                ingestion_id,
                False,
                {"dataset": dataset, "raw_path": raw_path, "sha256": sha, "exception": str(e), "traceback": tb},
            )
        except Exception:
            pass
        return {"ok": False, "error": "exception", "exception": str(e), "traceback": tb}


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
