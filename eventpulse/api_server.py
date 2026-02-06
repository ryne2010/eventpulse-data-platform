from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from redis import Redis
from rq import Queue

from .config import settings
from .db import get_ingestion, get_quality_report, init_db, list_ingestions
from .ingest import create_ingestion_record
from .jobs import process_ingestion
from .loaders.postgres import curated_table_exists, sample_curated, sample_curated_for_ingestion
from .demo.real_estate import generate_recorder_sales


app = FastAPI(title="EventPulse Data Platform", version="0.2.0")

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = (APP_DIR.parent / "web").resolve()
DIST_DIR = (WEB_DIR / "dist").resolve()

redis_conn = Redis.from_url(settings.redis_url)
queue = Queue("eventpulse", connection=redis_conn)


@app.on_event("startup")
def _startup():
    os.makedirs(settings.raw_data_dir, exist_ok=True)
    os.makedirs(settings.contracts_dir, exist_ok=True)
    os.makedirs(settings.incoming_dir, exist_ok=True)
    os.makedirs(settings.archive_dir, exist_ok=True)
    init_db()


if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
def root() -> Any:
    """Serve the React UI if built, otherwise fall back to a tiny landing page."""
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))

    return HTMLResponse(
        "<html><head><title>EventPulse</title></head>"
        "<body style='font-family: ui-sans-serif, system-ui; max-width: 860px; margin: 2rem auto;'>"
        "<h1>EventPulse Data Platform</h1>"
        "<p>UI not built. See README for <code>pnpm dev</code> / <code>pnpm build</code>.</p>"
        "<ul>"
        "<li><a href='/docs'>OpenAPI docs</a></li>"
        "<li><a href='/healthz'>Health</a></li>"
        "<li><code>POST /api/ingest/from_path</code></li>"
        "<li><code>GET /api/ingestions</code></li>"
        "</ul></body></html>"
    )


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> Dict[str, Any]:
    """Small diagnostic endpoint (used by the React UI and by smoke tests)."""
    return {
        "ok": True,
        "version": app.version,
        "runtime": {
            "queue": "eventpulse",
            "raw_data_dir": settings.raw_data_dir,
            "contracts_dir": settings.contracts_dir,
            "incoming_dir": settings.incoming_dir,
            "archive_dir": settings.archive_dir,
        },
    }


class IngestFromPathRequest(BaseModel):
    dataset: str
    relative_path: str
    source: Optional[str] = None


@app.post("/api/ingest/from_path")
def ingest_from_path(req: IngestFromPathRequest) -> Dict[str, Any]:
    # Restrict to INCOMING_DIR for safety
    src_path = os.path.abspath(os.path.join(settings.incoming_dir, req.relative_path))
    if not src_path.startswith(os.path.abspath(settings.incoming_dir) + os.sep) and src_path != os.path.abspath(settings.incoming_dir):
        raise HTTPException(status_code=400, detail="Path must be under INCOMING_DIR")

    if not os.path.exists(src_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.relative_path}")

    ingestion_id = create_ingestion_record(req.dataset, req.source, src_path)

    # Archive the incoming file (so watcher won't re-ingest)
    dst = os.path.join(settings.archive_dir, os.path.basename(src_path))
    try:
        shutil.move(src_path, dst)
    except Exception:
        # ignore if move fails; raw copy already exists
        pass

    job = queue.enqueue(process_ingestion, ingestion_id)
    return {"ok": True, "ingestion_id": ingestion_id, "job_id": job.id}


@app.get("/api/ingestions")
def api_list_ingestions(limit: int = 50) -> Dict[str, Any]:
    limit = max(1, min(limit, 200))
    items = list_ingestions(limit=limit)
    # convert datetimes to strings for JSON
    for it in items:
        for k in ("received_at", "processed_at"):
            if it.get(k):
                it[k] = it[k].isoformat()
    return {"items": items}


@app.get("/api/ingestions/{ingestion_id}")
def api_get_ingestion(ingestion_id: str) -> Dict[str, Any]:
    ingestion = get_ingestion(ingestion_id)
    if not ingestion:
        raise HTTPException(status_code=404, detail="Not found")
    for k in ("received_at", "processed_at"):
        if ingestion.get(k):
            ingestion[k] = ingestion[k].isoformat()
    quality = get_quality_report(ingestion_id)
    return {"ingestion": ingestion, "quality_report": quality}


@app.get("/api/ingestions/{ingestion_id}/preview")
def ingestion_preview(ingestion_id: str, limit: int = 10) -> Dict[str, Any]:
    """Preview the curated rows produced by a specific ingestion (if any)."""
    limit = max(1, min(limit, 50))
    ingestion = get_ingestion(ingestion_id)
    if not ingestion:
        raise HTTPException(status_code=404, detail="Not found")

    dataset = ingestion["dataset"]
    try:
        if not curated_table_exists(dataset):
            return {"ingestion_id": ingestion_id, "dataset": dataset, "table_exists": False, "rows": [], "limit": limit}
        rows = sample_curated_for_ingestion(dataset, ingestion_id=ingestion_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch ingestion preview: {e}")

    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return {"ingestion_id": ingestion_id, "dataset": dataset, "table_exists": True, "rows": rows, "limit": limit}


@app.post("/api/ingestions/{ingestion_id}/replay")
def replay(ingestion_id: str) -> Dict[str, Any]:
    ingestion = get_ingestion(ingestion_id)
    if not ingestion:
        raise HTTPException(status_code=404, detail="Not found")
    job = queue.enqueue(process_ingestion, ingestion_id)
    return {"ok": True, "job_id": job.id}


@app.get("/api/datasets/{dataset}/curated/sample")
def curated_sample(dataset: str, limit: int = 20) -> Dict[str, Any]:
    limit = max(1, min(limit, 200))
    try:
        if not curated_table_exists(dataset):
            return {"rows": [], "limit": limit, "table_exists": False}
        rows = sample_curated(dataset, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Preserve unexpected errors as 500s (helps debugging).
        raise HTTPException(status_code=500, detail=f"Failed to fetch curated sample: {e}")
    # Convert UUID/datetime for JSON
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return {"rows": rows, "limit": limit, "table_exists": True}


def _csv_escape(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    if any(ch in s for ch in [",", "\n", "\r", '"']):
        s = '"' + s.replace('"', '""') + '"'
    return s


@app.get("/api/demo/real_estate/recorder_sales")
def demo_recorder_sales(limit: int = 200) -> Dict[str, Any]:
    limit = max(10, min(limit, 2000))
    return generate_recorder_sales(limit=limit)


@app.post("/api/demo/seed/parcels")
def seed_parcels(limit: int = 50, per_ingestion_max: int = 15) -> Dict[str, Any]:
    """Seed 50 synthetic recorder-sales rows into the parcels pipeline.

    Writes a CSV into INCOMING_DIR, then enqueues a normal ingestion job so the
    data flows through raw/quality/drift/curated like any other dataset.
    """
    limit = max(1, min(limit, 50))
    per_ingestion_max = max(1, min(per_ingestion_max, 15))

    seed_id = uuid.uuid4().hex[:8]
    demo = generate_recorder_sales(limit=limit, parcel_id_prefix=f"BACA{seed_id}")

    ingestions = []

    cols = [
        "parcel_id",
        "county",
        "situs_address",
        "city",
        "state",
        "zip",
        "lat",
        "lon",
        "sale_date",
        "recording_date",
        "sale_price",
        "deed_type",
        "doc_number",
        "book",
        "page",
        "grantor",
        "grantee",
        "year_built",
        "bedrooms",
        "bathrooms",
        "building_sqft",
        "lot_sqft",
        "assessed_value",
        "land_use",
        "updated_at",
    ]

    rows = demo["rows"]
    for part_idx in range(0, len(rows), per_ingestion_max):
        chunk = rows[part_idx : part_idx + per_ingestion_max]
        filename = f"parcels_recorder_seed_{seed_id}_{(part_idx // per_ingestion_max) + 1}.csv"
        tmp_path = os.path.join(settings.incoming_dir, filename)

        # Use CSV (supported without extra deps).
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")
            for r in chunk:
                row = {
                    "parcel_id": r["parcel_id"],
                    "county": "Baca",
                    "situs_address": r["situs_address"],
                    "city": r["city"],
                    "state": r["state"],
                    "zip": r["zip"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "sale_date": r["sale_date"] + "T00:00:00Z",
                    "recording_date": r["recording_date"] + "T00:00:00Z",
                    "sale_price": r["sale_price"],
                    "deed_type": r["deed_type"],
                    "doc_number": r["doc_number"],
                    "book": r["book"],
                    "page": r["page"],
                    "grantor": r["grantor"],
                    "grantee": r["grantee"],
                    "year_built": r["year_built"],
                    "bedrooms": r["bedrooms"],
                    "bathrooms": r["bathrooms"],
                    "building_sqft": r["building_sqft"],
                    "lot_sqft": r["lot_sqft"],
                    "assessed_value": r["sale_price"],
                    "land_use": "residential",
                    "updated_at": r["recording_date"] + "T00:00:00Z",
                }
                f.write(",".join(_csv_escape(row[c]) for c in cols) + "\n")

        ingestion_id = create_ingestion_record("parcels", source=f"seed:{seed_id}", src_path=tmp_path)

        dst = os.path.join(settings.archive_dir, os.path.basename(tmp_path))
        try:
            shutil.move(tmp_path, dst)
        except Exception:
            pass

        job = queue.enqueue(process_ingestion, ingestion_id)
        ingestions.append({"ingestion_id": ingestion_id, "job_id": job.id, "rows": len(chunk)})

    return {"ok": True, "seed_id": seed_id, "rows": limit, "per_ingestion_max": per_ingestion_max, "ingestions": ingestions}


# SPA fallback (serves React Router paths)
@app.get("/{path:path}")
def spa_fallback(path: str) -> Any:
    if path.startswith(("api", "docs", "openapi", "redoc", "healthz")):
        raise HTTPException(status_code=404)

    target = DIST_DIR / path
    if target.exists() and target.is_file():
        return FileResponse(str(target))

    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))

    raise HTTPException(status_code=404, detail="UI not built")
