from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import normalize_ingest_auth_mode, normalize_task_auth_mode, settings
from .contracts import load_contract_with_meta, parse_contract_yaml
from .db import (
    db_ping,
    create_replay_ingestion,
    insert_ingestion_from_gcs_event,
    get_ingestion,
    get_lineage_artifact,
    get_quality_report,
    init_db,
    list_ingestions,
    list_schema_history,
    list_dataset_summaries,
    get_platform_stats,
    get_db_stats,
    prune_audit_events,
    prune_ingestions,
    reclaim_stuck_ingestions,
    insert_audit_event,
    list_audit_events,
    get_quality_trend,
)
from .ingest import create_ingestion_record
from .gcp_rest import (
    GCSDownloadError,
    GCSObjectMetadataError,
    gcs_download_file,
    gcs_generate_v4_signed_url,
    gcs_get_object,
)
from .logging_setup import setup_logging
from .middleware import request_context_middleware
from .gcs_events import build_raw_object_name, is_valid_sha256_hex, parse_raw_object_name
from .naming import normalize_dataset_name
from .queueing import enqueue_ingestion
from .loaders.postgres import (
    curated_table_exists,
    sample_curated,
    sample_curated_for_ingestion,
    list_dataset_marts,
    sample_view,
    view_exists,
)


class SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA fallback.

    - Serves real files from the built UI dist directory.
    - Falls back to index.html for client-side routes (no extension)
      while preserving proper 404s for /api/* and missing assets.

    This avoids a common Cloud Run gotcha: refreshing on /ingestions/123 should
    still render the SPA instead of returning 404.
    """

    async def get_response(self, path: str, scope: Any) -> Any:
        # Never "SPA fallback" API/internal paths.
        normalized = (path or "").lstrip("/")
        first = normalized.split("/", 1)[0] if normalized else ""
        if first in {"api", "internal"}:
            return await super().get_response(path, scope)

        # If the request looks like a file (has an extension), keep the 404.
        last = normalized.split("/")[-1] if normalized else ""
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and last and "." not in last:
                return await super().get_response("index.html", scope)
            raise


setup_logging(log_level=settings.log_level, log_format=settings.log_format)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """App lifecycle hook for startup checks and DB initialization."""

    init_db()

    mode = normalize_task_auth_mode(settings.task_auth_mode)
    if mode == "iam" and not settings.task_token:
        logger.warning(
            "TASK_AUTH_MODE=iam with no TASK_TOKEN; ensure Cloud Run requires authentication (no unauth) or internal endpoints may be exposed",
            extra={"task_auth_mode": mode},
        )

    if settings.enable_signed_urls and mode != "iam" and not settings.task_token:
        logger.warning(
            "ENABLE_SIGNED_URLS=true but internal auth is not enabled; signed URL minting should be protected (TASK_AUTH_MODE=iam or TASK_TOKEN)",
            extra={"task_auth_mode": mode},
        )

    if settings.enable_gcs_event_ingestion:
        if mode != "iam" or settings.task_token:
            logger.warning(
                "ENABLE_GCS_EVENT_INGESTION=true requires TASK_AUTH_MODE=iam with TASK_TOKEN unset (Pub/Sub push cannot send X-Task-Token)",
                extra={"task_auth_mode": mode},
            )

    yield


app = FastAPI(title="EventPulse Data Platform", version=__version__, lifespan=_lifespan)
app.middleware("http")(request_context_middleware)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Add baseline security headers.

    We keep the SPA's policy tight, but allow the minimum external origins
    required for core features:

    - Browser-based GCS signed URL uploads: https://storage.googleapis.com
    - FastAPI Swagger UI / Redoc assets (CDN): https://cdn.jsdelivr.net (docs routes only)

    If you front this service with an auth proxy / CDN / WAF, you can also
    enforce these at the ingress/load-balancer layer.
    """

    response = await call_next(request)

    # Prevent content-type sniffing.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")

    # Prevent clickjacking.
    response.headers.setdefault("X-Frame-Options", "DENY")

    # Avoid leaking URL paths via Referer.
    response.headers.setdefault("Referrer-Policy", "no-referrer")

    # Lock down powerful APIs (UI does not require these today).
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )

    # HSTS only makes sense behind HTTPS (Cloud Run sets X-Forwarded-Proto=https).
    proto = request.headers.get("X-Forwarded-Proto") or request.url.scheme
    if proto == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    # Content Security Policy (single-origin SPA + API).
    #
    # Notes:
    # - We allow 'unsafe-inline' scripts/styles to support the small theme-boot script
    #   in Vite's index.html (prevents dark-mode flash).
    # - connect-src must allow storage.googleapis.com so the browser can PUT to
    #   GCS signed URLs (production-friendly uploads).
    # - Swagger/Redoc use CDN-hosted assets by default; we only allow the CDN
    #   on those documentation routes.
    path = request.url.path or ""
    is_api_docs = path.startswith("/docs") or path.startswith("/redoc")

    script_src = ["'self'", "'unsafe-inline'"]
    style_src = ["'self'", "'unsafe-inline'"]
    font_src = ["'self'", "data:"]
    connect_src = ["'self'", "https://storage.googleapis.com"]

    if is_api_docs:
        script_src.append("https://cdn.jsdelivr.net")
        style_src.append("https://cdn.jsdelivr.net")
        font_src.append("https://cdn.jsdelivr.net")

    csp = " ".join(
        [
            "default-src 'self';",
            "base-uri 'self';",
            "form-action 'self';",
            "frame-ancestors 'none';",
            "object-src 'none';",
            "img-src 'self' data: blob: https:;",
            f"font-src {' '.join(font_src)};",
            f"style-src {' '.join(style_src)};",
            f"script-src {' '.join(script_src)};",
            f"connect-src {' '.join(connect_src)};",
            "manifest-src 'self';",
        ]
    )

    response.headers.setdefault("Content-Security-Policy", csp)

    return response


# -----------------------------
# Health
# -----------------------------


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True, "version": __version__}


# API-prefixed health alias (useful for managed probes / shared ingress rules).
@app.get("/api/healthz")
def api_healthz() -> Dict[str, Any]:
    return healthz()


# Common default used by Makefile + CI
@app.get("/health")
def health() -> Dict[str, Any]:
    return healthz()


@app.get("/readyz")
def readyz() -> Dict[str, Any]:
    db_ok = db_ping()

    # Queue readiness: only check Redis if we depend on it.
    queue_ok = True
    queue_detail: str = settings.queue_backend
    if settings.queue_backend == "redis":
        try:
            from redis import Redis

            Redis.from_url(settings.redis_url).ping()
            queue_detail = "redis:ok"
        except Exception as e:
            queue_ok = False
            queue_detail = f"redis:error:{e}"

    storage_detail = settings.storage_backend
    if settings.storage_backend == "gcs":
        if not settings.raw_gcs_bucket:
            storage_detail = "gcs:missing_bucket"

    ok = bool(db_ok and queue_ok)
    return {
        "ok": ok,
        "db": "ok" if db_ok else "error",
        "queue": queue_detail,
        "storage": storage_detail,
        "version": __version__,
    }


# -----------------------------
# Meta
# -----------------------------


@app.get("/api/meta")
def meta() -> Dict[str, Any]:
    """Return build + runtime metadata for the UI and troubleshooting."""

    return {
        "ok": True,
        "version": __version__,
        "runtime": {
            "queue": settings.queue_backend,
            "storage_backend": settings.storage_backend,
            "raw_data_dir": settings.raw_data_dir,
            "raw_gcs_bucket": settings.raw_gcs_bucket,
            "raw_gcs_prefix": settings.raw_gcs_prefix,
            "contracts_dir": settings.contracts_dir,
            "incoming_dir": settings.incoming_dir,
            "archive_dir": settings.archive_dir,
            "task_auth_mode": normalize_task_auth_mode(settings.task_auth_mode),
            "ingest_auth_mode": normalize_ingest_auth_mode(settings.ingest_auth_mode),
            "ingest_token_configured": bool(settings.ingest_token),
            "enable_signed_urls": settings.enable_signed_urls,
            "signed_url_expires_seconds": settings.signed_url_expires_seconds,
            "require_signed_url_sha256": settings.require_signed_url_sha256,
            "enable_gcs_event_ingestion": settings.enable_gcs_event_ingestion,
            "enable_demo_endpoints": settings.enable_demo_endpoints,
            "enable_ingest_from_path": settings.enable_ingest_from_path,
            "enable_contract_write": settings.enable_contract_write,
            "enable_incoming_list": settings.enable_incoming_list,
        },
    }


@app.get("/api/ping")
def api_ping() -> Dict[str, Any]:
    """Lightweight ping endpoint used by the UI Ops page.

    This is intentionally *not* the readiness probe (see /readyz). It gives the
    UI a small, human-friendly signal that core dependencies are reachable.
    """

    db_ok = db_ping()

    queue_ok = True
    queue_detail: str = settings.queue_backend
    if settings.queue_backend == "redis":
        try:
            from redis import Redis

            Redis.from_url(settings.redis_url).ping()
            queue_detail = "redis:ok"
        except Exception as e:
            queue_ok = False
            queue_detail = f"redis:error:{e}"

    return {
        "ok": bool(db_ok and queue_ok),
        "db": bool(db_ok),
        "queue": queue_detail,
        "version": __version__,
    }


@app.get("/api/stats")
def api_stats(hours: int = 24) -> Dict[str, Any]:
    """Operational stats for the dashboard UI."""

    return get_platform_stats(hours=hours)


# -----------------------------
# Observability / governance
# -----------------------------


@app.get("/api/audit_events")
def api_audit_events(
    limit: int = 200,
    dataset: Optional[str] = None,
    ingestion_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
) -> Dict[str, Any]:
    """List recent audit events (newest first)."""

    items = list_audit_events(
        limit=limit, dataset=dataset, ingestion_id=ingestion_id, event_type=event_type, actor=actor
    )
    return {"items": items}


@app.get("/api/trends/quality")
def api_quality_trend(
    hours: int = 168,
    bucket_minutes: int = 60,
    dataset: Optional[str] = None,
) -> Dict[str, Any]:
    """Quality pass/fail trends for UI charts."""

    try:
        return get_quality_trend(dataset=dataset, hours=hours, bucket_minutes=bucket_minutes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# -----------------------------
# Ingestion endpoints
# -----------------------------


@app.get("/api/incoming/list")
def api_incoming_list(
    request: Request,
    limit: int = 200,
) -> Dict[str, Any]:
    """List files available under INCOMING_DIR.

    This is a local-dev convenience for backfills using /api/ingest/from_path.

    Security:
    - gated behind ENABLE_INCOMING_LIST=true
    - requires internal auth (TASK_TOKEN or Cloud Run IAM)
    """

    if not settings.enable_incoming_list:
        raise HTTPException(status_code=404, detail="incoming list disabled")

    _require_internal_auth(request)

    limit = max(1, min(int(limit), 1000))

    root = Path(settings.incoming_dir).resolve()
    if not root.exists():
        return {"items": [], "limit": limit}

    items: list[dict[str, Any]] = []
    try:
        for p in sorted(root.rglob("*")):
            if len(items) >= limit:
                break
            if p.is_symlink():
                continue
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            # Skip obvious dotfiles
            if any(part.startswith(".") for part in Path(rel).parts):
                continue
            items.append(
                {
                    "relative_path": rel,
                    "size_bytes": int(p.stat().st_size),
                    "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to list incoming dir: {e}")

    return {"items": items, "limit": limit}


@app.post("/api/ingest/from_path")
def ingest_from_path(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    if not settings.enable_ingest_from_path:
        raise HTTPException(status_code=404, detail="ingest/from_path disabled")

    # This endpoint reads from the container filesystem and should never be exposed
    # publicly. We gate it behind the same internal auth model as other privileged
    # ingestion helpers.
    _require_internal_auth(request)

    dataset = normalize_dataset_name(str(payload.get("dataset") or ""))
    relative_path = str(payload.get("relative_path") or "")
    source = payload.get("source")

    incoming_root = Path(settings.incoming_dir).resolve()
    src = (incoming_root / relative_path).resolve()

    # Prevent path traversal
    try:
        src.relative_to(incoming_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="relative_path escapes INCOMING_DIR")

    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {relative_path}")

    try:
        ingestion_id = create_ingestion_record(dataset, source, str(src))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Archive the source file to avoid re-processing.
    _archive_incoming_file(src, ingestion_id=ingestion_id, dataset=dataset)

    enq = enqueue_ingestion(ingestion_id, request_base_url=str(request.base_url))
    ing = get_ingestion(ingestion_id)
    if not ing:
        raise HTTPException(status_code=500, detail="ingestion record missing after create")

    # Best-effort audit trail (does not block ingestion)
    try:
        insert_audit_event(
            event_type="ingestion.received",
            actor=_actor_from_request(request) or "api",
            dataset=dataset,
            ingestion_id=ingestion_id,
            details={"method": "from_path", "source": source, "relative_path": relative_path},
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "ingestion_id": ingestion_id})

    return {
        "ingestion_id": ingestion_id,
        "job_backend": enq.backend,
        "job_id": enq.id,
        "raw_path": ing["raw_path"],
    }


@app.post("/api/ingest/upload")
async def ingest_upload(
    request: Request,
    dataset: str,
    filename: str,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a file to ingest.

    This endpoint intentionally avoids multipart parsing to keep dependencies small.

    Example:
      curl -X POST \
        'http://localhost:8081/api/ingest/upload?dataset=parcels&filename=parcels.xlsx&source=curl' \
        -H 'Content-Type: application/octet-stream' \
        --data-binary @./data/samples/parcels_baseline.xlsx
    """

    _require_ingest_auth(request)

    dataset = normalize_dataset_name(dataset)
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise HTTPException(status_code=400, detail="filename is required")

    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in settings.allowed_file_exts:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {ext}")

    tmp_dir = Path("/tmp") / "eventpulse_uploads" / uuid.uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / safe_name

    # Stream request body to disk (avoid holding large files in memory)
    max_bytes = settings.max_file_mb * 1024 * 1024
    written = 0
    try:
        with open(tmp_path, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"file too large (> {settings.max_file_mb} MB)")
                f.write(chunk)
        try:
            ingestion_id = create_ingestion_record(dataset, source, str(tmp_path))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        enq = enqueue_ingestion(ingestion_id, request_base_url=str(request.base_url))
        ing = get_ingestion(ingestion_id)
        if not ing:
            raise HTTPException(status_code=500, detail="ingestion record missing after create")

        # Best-effort audit trail (does not block ingestion)
        try:
            insert_audit_event(
                event_type="ingestion.received",
                actor=_actor_from_request(request) or "api",
                dataset=dataset,
                ingestion_id=ingestion_id,
                details={"method": "upload", "source": source, "filename": safe_name, "size_bytes": written},
            )
        except Exception as e:
            logger.warning("audit insert failed", extra={"error": str(e), "ingestion_id": ingestion_id})

        return {
            "ingestion_id": ingestion_id,
            "job_backend": enq.backend,
            "job_id": enq.id,
            "raw_path": ing["raw_path"],
        }

    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@app.post("/api/uploads/gcs_signed_url")
def gcs_signed_url(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Mint a short-lived V4 signed URL for direct upload to the raw landing bucket.

    Recommended Cloud Run path for large files:
      client -> PUT signed URL -> GCS -> (optional) event -> ingestion -> async processing

    Payload:
      {
        "dataset": "parcels",
        "filename": "parcels.xlsx",
        "sha256": "<64-char hex>",
        "source": "curl"  # optional
      }

    Response includes:
      - upload_url (PUT)
      - required_headers (must be provided verbatim)
      - gcs_uri (gs://... raw object)

    Security:
      This endpoint is protected by the same internal auth model as task/admin
      endpoints (TASK_AUTH_MODE token/iam).
    """

    if settings.storage_backend != "gcs":
        raise HTTPException(status_code=400, detail="gcs_signed_url requires STORAGE_BACKEND=gcs")
    if not settings.enable_signed_urls:
        raise HTTPException(status_code=404, detail="signed URL endpoint disabled")
    if not settings.raw_gcs_bucket:
        raise HTTPException(status_code=500, detail="RAW_GCS_BUCKET is not configured")

    _require_internal_auth(request)

    dataset = normalize_dataset_name(str(payload.get("dataset") or ""))
    filename = os.path.basename(str(payload.get("filename") or ""))
    source = str(payload.get("source") or "").strip() or None

    sha256 = str(payload.get("sha256") or payload.get("sha") or "").lower().strip()

    # In event-driven mode, the object name is parsed to register ingestions; it *must*
    # contain the actual SHA256.
    needs_sha = bool(settings.require_signed_url_sha256 or settings.enable_gcs_event_ingestion)
    if needs_sha and not is_valid_sha256_hex(sha256):
        raise HTTPException(status_code=400, detail="sha256 (64-char hex) is required for signed uploads")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.allowed_file_exts:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {ext}")

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    upload_id: Optional[str] = None
    if is_valid_sha256_hex(sha256):
        object_name = build_raw_object_name(
            raw_prefix=settings.raw_gcs_prefix,
            dataset=dataset,
            day=day,
            sha256=sha256,
            ext=ext,
        )
    else:
        # Non-canonical object name (still within the raw prefix) for cases where the
        # client can't compute SHA256. This is only supported when event-driven ingestion
        # is disabled; the object must later be registered via /api/ingest/from_gcs which
        # will copy into the canonical raw landing zone.
        upload_id = uuid.uuid4().hex
        prefix = (settings.raw_gcs_prefix or "").strip("/")
        if prefix:
            object_name = f"{prefix}/{dataset}/{day}/upload-{upload_id}{ext}"
        else:
            object_name = f"{dataset}/{day}/upload-{upload_id}{ext}"

    required_headers: Dict[str, str] = {
        "Content-Type": "application/octet-stream",
        "x-goog-meta-original-filename": filename,
        "x-goog-meta-dataset": dataset,
    }
    if source:
        required_headers["x-goog-meta-source"] = source
    if sha256:
        required_headers["x-goog-meta-sha256"] = sha256
    if upload_id:
        required_headers["x-goog-meta-upload-id"] = upload_id

    upload_url = gcs_generate_v4_signed_url(
        bucket=settings.raw_gcs_bucket,
        object_name=object_name,
        method="PUT",
        expires_seconds=settings.signed_url_expires_seconds,
        headers_to_sign=required_headers,
    )

    # Best-effort audit trail (does not block minting)
    try:
        insert_audit_event(
            event_type="upload.signed_url_issued",
            actor=_actor_from_request(request) or "api",
            dataset=dataset,
            details={
                "object_name": object_name,
                "gcs_bucket": settings.raw_gcs_bucket,
                "expires_in_seconds": settings.signed_url_expires_seconds,
                "event_ingestion_enabled": settings.enable_gcs_event_ingestion,
                "has_sha256": bool(sha256),
            },
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "object_name": object_name})

    return {
        "method": "PUT",
        "upload_url": upload_url,
        "required_headers": required_headers,
        "gcs_uri": f"gs://{settings.raw_gcs_bucket}/{object_name}",
        "object_name": object_name,
        "expires_in_seconds": settings.signed_url_expires_seconds,
        "event_ingestion_enabled": settings.enable_gcs_event_ingestion,
    }


@app.post("/api/ingest/from_gcs")
def ingest_from_gcs(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Register an ingestion from a GCS object.

    Two modes:
    1) **Fast path**: if the object already lives in the configured raw landing
       zone naming scheme (RAW_GCS_BUCKET/RAW_GCS_PREFIX/<dataset>/<day>/<sha><ext>),
       register it without copying.
    2) **Copy path**: otherwise, download to /tmp and re-upload into the raw
       landing zone (useful for ad-hoc uploads).

    Security:
      This endpoint is protected by the internal auth model (TASK_AUTH_MODE
      token/iam) because it causes the service account to read from GCS.

    Payload:
      {"dataset": "parcels", "gcs_uri": "gs://bucket/path/file.xlsx", "source": "gsutil"}
    """

    if settings.storage_backend != "gcs":
        raise HTTPException(status_code=400, detail="/api/ingest/from_gcs requires STORAGE_BACKEND=gcs")

    _require_internal_auth(request)

    dataset = normalize_dataset_name(str(payload.get("dataset") or ""))
    gcs_uri = str(payload.get("gcs_uri") or "")
    source = str(payload.get("source") or "") or None

    if not gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="gcs_uri must be a gs:// URI")

    try:
        bucket, object_name = _parse_gs_uri(gcs_uri)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    filename = os.path.basename(object_name)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in settings.allowed_file_exts:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {ext}")

    # Fast path: if the object already matches the raw landing zone scheme, avoid
    # the download+reupload copy.
    if settings.raw_gcs_bucket and bucket == settings.raw_gcs_bucket:
        ref = parse_raw_object_name(raw_prefix=settings.raw_gcs_prefix, object_name=object_name)
        if ref and normalize_dataset_name(ref.dataset) == dataset:
            try:
                obj = gcs_get_object(bucket, ref.object_name)
                gen = obj.get("generation")
                raw_generation = int(gen) if gen is not None else None

                if raw_generation is not None:
                    md = obj.get("metadata") or {}
                    if isinstance(md, dict):
                        filename = str(
                            md.get("original-filename")
                            or md.get("original_filename")
                            or md.get("originalFilename")
                            or filename
                        )
                        if not source:
                            source = str(md.get("source") or md.get("ingest-source") or "gcs")

                    ingestion_uuid, created = insert_ingestion_from_gcs_event(
                        dataset=dataset,
                        source=source,
                        filename=filename,
                        file_ext=ref.ext,
                        sha256=ref.sha256,
                        raw_path=f"gs://{bucket}/{ref.object_name}",
                        raw_generation=raw_generation,
                    )

                    enq = enqueue_ingestion(str(ingestion_uuid), request_base_url=str(request.base_url))

                    # Best-effort audit trail (does not block ingestion)
                    try:
                        insert_audit_event(
                            event_type="ingestion.received",
                            actor=_actor_from_request(request) or "api",
                            dataset=dataset,
                            ingestion_id=str(ingestion_uuid),
                            details={
                                "method": "from_gcs_fastpath",
                                "gcs_uri": gcs_uri,
                                "raw_path": f"gs://{bucket}/{ref.object_name}",
                                "raw_generation": raw_generation,
                                "created": created,
                            },
                        )
                    except Exception as e:
                        logger.warning(
                            "audit insert failed",
                            extra={"error": str(e), "ingestion_id": str(ingestion_uuid), "gcs_uri": gcs_uri},
                        )

                    return {
                        "ingestion_id": str(ingestion_uuid),
                        "status": "RECEIVED",
                        "raw_path": f"gs://{bucket}/{ref.object_name}",
                        "raw_generation": raw_generation,
                        "created": created,
                        "registered_existing_raw_object": True,
                        "job_backend": enq.backend,
                        "job_id": enq.id,
                    }

            except Exception as e:
                logger.warning(
                    "from_gcs fast-path failed; falling back to copy",
                    extra={"error": str(e), "gcs_uri": gcs_uri},
                )

    # Copy path: download to temp and ingest into the canonical raw landing zone.
    tmp_dir = tempfile.mkdtemp(prefix="eventpulse_from_gcs_")
    try:
        tmp_path = os.path.join(tmp_dir, filename)

        try:
            gcs_download_file(bucket, object_name, tmp_path)
        except GCSDownloadError as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="GCS object not found")
            raise HTTPException(status_code=502, detail=f"GCS download failed: {e}")

        # Create ingestion record (this stores into the immutable raw landing zone).
        ingestion_id = create_ingestion_record(dataset, source, tmp_path)

        enq = enqueue_ingestion(ingestion_id, request_base_url=str(request.base_url))

        # Best-effort audit trail (does not block ingestion)
        try:
            insert_audit_event(
                event_type="ingestion.received",
                actor=_actor_from_request(request) or "api",
                dataset=dataset,
                ingestion_id=ingestion_id,
                details={"method": "from_gcs_copy", "gcs_uri": gcs_uri, "source": source},
            )
        except Exception as e:
            logger.warning(
                "audit insert failed", extra={"error": str(e), "ingestion_id": ingestion_id, "gcs_uri": gcs_uri}
            )

        return {
            "ingestion_id": ingestion_id,
            "status": "RECEIVED",
            "raw_path": None,
            "registered_existing_raw_object": False,
            "job_backend": enq.backend,
            "job_id": enq.id,
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# -----------------------------
# Internal endpoints (tasks/admin)
# -----------------------------


def _require_ingest_auth(request: Request) -> None:
    """Authorize access to the public ingest endpoint.

    This is intentionally separate from the internal task/admin auth model.
    In token mode, callers must include X-Ingest-Token (or Authorization: Bearer).
    """

    mode = normalize_ingest_auth_mode(settings.ingest_auth_mode)
    if mode != "token":
        return

    # Misconfiguration guard: token mode enabled but no token value set.
    # Safer to *disable* the endpoint than accept unauthenticated uploads.
    if not settings.ingest_token:
        raise HTTPException(status_code=404, detail="ingest endpoint disabled")

    provided = request.headers.get("x-ingest-token") or request.headers.get("X-Ingest-Token")

    # Also accept standard Authorization: Bearer <token>
    if not provided:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and str(auth).lower().startswith("bearer "):
            provided = str(auth).split(" ", 1)[1].strip()

    if not provided or not secrets.compare_digest(str(provided), str(settings.ingest_token)):
        raise HTTPException(status_code=403, detail="forbidden")


def _require_internal_auth(request: Request) -> None:
    """Authorize access to internal endpoints.

    In "token" mode, we require X-Task-Token.
    In "iam" mode, we rely on Cloud Run IAM (OIDC) and do not require a header.

    Defense-in-depth: if TASK_TOKEN is set, we will still validate it even in
    IAM mode.
    """

    mode = normalize_task_auth_mode(settings.task_auth_mode)

    provided = request.headers.get("x-task-token") or request.headers.get("X-Task-Token")

    # Always enforce token if configured.
    if settings.task_token:
        if not provided or not secrets.compare_digest(str(provided), str(settings.task_token)):
            raise HTTPException(status_code=403, detail="forbidden")
        return

    # Token not configured → only allow in IAM mode.
    if mode != "iam":
        raise HTTPException(status_code=404, detail="internal endpoints disabled")


def _actor_from_request(request: Request) -> Optional[str]:
    """Best-effort actor extraction for audit events."""

    # Explicit caller-supplied label (e.g. UI sets X-Actor: ui)
    actor = request.headers.get("x-actor") or request.headers.get("X-Actor")
    if actor and str(actor).strip():
        return str(actor).strip()[:200]

    # Cloud Run IAM header (when service requires authentication)
    email = request.headers.get("x-goog-authenticated-user-email") or request.headers.get(
        "X-Goog-Authenticated-User-Email"
    )
    if email and str(email).strip():
        raw = str(email).strip()
        # Format is often: "accounts.google.com:someone@example.com"
        if ":" in raw:
            raw = raw.split(":", 1)[1]
        return raw[:200]

    return None


def _unwrap_pubsub_push(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap Pub/Sub push envelope to the embedded event JSON."""

    msg = payload.get("message")
    if isinstance(msg, dict) and msg.get("data"):
        data_b64 = msg.get("data")
        try:
            decoded = base64.b64decode(str(data_b64)).decode("utf-8")
            return dict(json.loads(decoded))
        except Exception:
            # Fall back to returning the outer payload for debugging.
            return payload

    return payload


@app.post("/internal/events/gcs_finalize", include_in_schema=False)
def internal_gcs_finalize(request: Request, payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    """Handle GCS object finalize events delivered via Pub/Sub push.

    This endpoint is meant to be invoked by infrastructure (Pub/Sub push / Eventarc)
    and is disabled by default.

    Notes:
    - Event delivery is at-least-once; ingestion insert is idempotent.
    - Only objects matching the raw landing zone naming scheme are accepted:
      RAW_GCS_PREFIX/<dataset>/<YYYY-MM-DD>/<sha256><ext>
    """

    if not settings.enable_gcs_event_ingestion:
        raise HTTPException(status_code=404, detail="gcs event ingestion disabled")

    _require_internal_auth(request)

    event = _unwrap_pubsub_push(payload)

    bucket = str(event.get("bucket") or "")
    name = str(event.get("name") or event.get("objectId") or "")
    generation_raw = event.get("generation") or event.get("objectGeneration")

    if not bucket or not name:
        raise HTTPException(status_code=400, detail="missing bucket/name")

    try:
        raw_generation = int(generation_raw) if generation_raw is not None else None
    except Exception:
        raw_generation = None

    if raw_generation is None:
        raise HTTPException(status_code=400, detail="missing generation")

    ref = parse_raw_object_name(raw_prefix=settings.raw_gcs_prefix, object_name=name)
    if not ref:
        # Ignore non-conforming objects (e.g., other prefixes).
        return JSONResponse({"ok": True, "ignored": True, "reason": "object_not_in_raw_prefix"}, status_code=200)

    original_filename = f"{ref.sha256}{ref.ext}"
    source = "gcs_event"

    # Best-effort metadata fetch (original filename + source).
    try:
        obj = gcs_get_object(bucket, ref.object_name)
        md = obj.get("metadata") or {}
        if isinstance(md, dict):
            original_filename = str(
                md.get("original-filename")
                or md.get("original_filename")
                or md.get("originalFilename")
                or original_filename
            )
            source = str(md.get("source") or md.get("ingest-source") or source)
    except GCSObjectMetadataError:
        pass
    except Exception as e:
        logger.warning(
            "gcs_event metadata lookup failed",
            extra={"error": str(e), "bucket": bucket, "object": ref.object_name},
        )

    ingestion_uuid, created = insert_ingestion_from_gcs_event(
        dataset=normalize_dataset_name(ref.dataset),
        source=source,
        filename=original_filename,
        file_ext=ref.ext,
        sha256=ref.sha256,
        raw_path=f"gs://{bucket}/{ref.object_name}",
        raw_generation=raw_generation,
    )

    enq = enqueue_ingestion(str(ingestion_uuid), request_base_url=str(request.base_url))

    # Best-effort audit trail (does not block ingestion)
    try:
        insert_audit_event(
            event_type="ingestion.received",
            actor=_actor_from_request(request) or "gcs_event",
            dataset=normalize_dataset_name(ref.dataset),
            ingestion_id=str(ingestion_uuid),
            details={
                "method": "gcs_finalize_event",
                "created": created,
                "raw_path": f"gs://{bucket}/{ref.object_name}",
                "raw_generation": raw_generation,
            },
        )
    except Exception as e:
        logger.warning(
            "audit insert failed",
            extra={"error": str(e), "ingestion_id": str(ingestion_uuid), "object": ref.object_name},
        )

    return JSONResponse(
        {
            "ok": True,
            "created": created,
            "ingestion_id": str(ingestion_uuid),
            "job_backend": enq.backend,
            "job_id": enq.id,
            "raw_path": f"gs://{bucket}/{ref.object_name}",
            "raw_generation": raw_generation,
        },
        status_code=200,
    )


# Internal endpoint for Cloud Tasks
@app.post("/internal/tasks/process_ingestion", include_in_schema=False)
def internal_process_task(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> JSONResponse:
    """Process an ingestion triggered by Cloud Tasks.

    Security model:
    - TASK_AUTH_MODE=token: endpoint can live on a public service but requires
      X-Task-Token matching TASK_TOKEN.
    - TASK_AUTH_MODE=iam: deploy Cloud Run with allow_unauthenticated=false;
      Cloud Tasks calls with OIDC tokens and no shared secret is required.
    """

    _require_internal_auth(request)

    ingestion_id = str(payload.get("ingestion_id") or "")
    if not ingestion_id:
        raise HTTPException(status_code=400, detail="ingestion_id is required")

    from .jobs import process_ingestion

    result = process_ingestion(ingestion_id)

    # If we hit an unexpected exception, return 500 so Cloud Tasks retries.
    if not result.get("ok") and result.get("error") == "exception":
        return JSONResponse(status_code=500, content=result)

    return JSONResponse(status_code=200, content=result)


@app.post("/internal/admin/reclaim_stuck", include_in_schema=False)
def internal_reclaim_stuck(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    """Reclaim ingestions stuck in PROCESSING and (optionally) re-enqueue them."""

    _require_internal_auth(request)

    older_than = int(payload.get("older_than_seconds") or settings.processing_ttl_seconds)
    limit = int(payload.get("limit") or settings.reclaim_max_per_run)
    reenqueue = bool(payload.get("reenqueue", True))

    reclaimed = reclaim_stuck_ingestions(older_than_seconds=older_than, limit=limit)

    requeued: list[dict[str, Any]] = []
    if reenqueue:
        for ing_id in reclaimed:
            try:
                enq = enqueue_ingestion(ing_id, request_base_url=str(request.base_url))
                requeued.append({"ingestion_id": ing_id, "job_backend": enq.backend, "job_id": enq.id})
            except Exception as e:
                # Don't fail the whole reclaim run.
                logger.exception("Failed to re-enqueue reclaimed ingestion", extra={"ingestion_id": ing_id})
                requeued.append({"ingestion_id": ing_id, "error": str(e)})

    # Best-effort audit trail (does not block reclaim)
    try:
        insert_audit_event(
            event_type="ops.reclaim_stuck",
            actor=_actor_from_request(request) or "ops",
            details={
                "older_than_seconds": older_than,
                "limit": limit,
                "reenqueue": reenqueue,
                "reclaimed_count": len(reclaimed),
                "reclaimed_sample": reclaimed[:10],
                "reenqueued_count": len([r for r in requeued if r.get("job_id")]),
                "reenqueue_errors": len([r for r in requeued if r.get("error")]),
            },
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "action": "reclaim_stuck"})

    return {
        "ok": True,
        "reclaimed": reclaimed,
        "reenqueued": requeued,
        "older_than_seconds": older_than,
        "limit": limit,
        "reenqueue": reenqueue,
    }


@app.get("/internal/admin/db_stats", include_in_schema=False)
def internal_db_stats(request: Request) -> Dict[str, Any]:
    """Return lightweight DB stats (sizes, row estimates)."""

    _require_internal_auth(request)
    return get_db_stats()


@app.post("/internal/admin/prune", include_in_schema=False)
def internal_prune(request: Request, payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    """Prune old operational rows (retention).

    This endpoint is intentionally conservative:
    - defaults to dry_run=true
    - requires an explicit confirm token for destructive runs
    """

    _require_internal_auth(request)

    dry_run = bool(payload.get("dry_run", True))
    confirm = str(payload.get("confirm") or "")
    if not dry_run and confirm.strip().upper() != "PRUNE":
        raise HTTPException(status_code=400, detail="confirm=PRUNE required when dry_run=false")

    audit_days = payload.get("audit_older_than_days")
    audit_limit = int(payload.get("audit_limit") or 50_000)

    ing_days = payload.get("ingestions_older_than_days")
    ing_limit = int(payload.get("ingestions_limit") or 5_000)

    result: Dict[str, Any] = {"ok": True, "dry_run": dry_run, "audit": None, "ingestions": None}

    if audit_days is not None:
        result["audit"] = prune_audit_events(
            older_than_days=int(audit_days),
            limit=audit_limit,
            dry_run=dry_run,
        )

    if ing_days is not None:
        result["ingestions"] = prune_ingestions(
            older_than_days=int(ing_days),
            limit=ing_limit,
            dry_run=dry_run,
        )

    # Best-effort audit trail (does not block prune)
    try:
        audit_summary = None
        if isinstance(result.get("audit"), dict):
            a = result["audit"]
            audit_summary = {
                "older_than_days": a.get("older_than_days"),
                "limit": a.get("limit"),
                "planned": a.get("planned"),
                "deleted": a.get("deleted"),
            }

        ing_summary = None
        if isinstance(result.get("ingestions"), dict):
            i = result["ingestions"]
            ing_summary = {
                "older_than_days": i.get("older_than_days"),
                "limit": i.get("limit"),
                "planned": i.get("planned"),
                "deleted": i.get("deleted"),
            }

        insert_audit_event(
            event_type="ops.prune",
            actor=_actor_from_request(request) or "ops",
            details={
                "dry_run": dry_run,
                "audit": audit_summary,
                "ingestions": ing_summary,
            },
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "action": "prune"})

    return result


# -----------------------------
# Ingestion records
# -----------------------------


@app.get("/api/ingestions")
def api_list_ingestions(limit: int = 50, dataset: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    items = list_ingestions(limit=limit, dataset=dataset, status=status)
    return {"items": [_serialize_ingestion(it) for it in items]}


@app.get("/api/ingestions/{ingestion_id}")
def api_get_ingestion(ingestion_id: str) -> Dict[str, Any]:
    ing = get_ingestion(ingestion_id)
    if not ing:
        raise HTTPException(status_code=404, detail="not found")
    qr = get_quality_report(ingestion_id)
    return {
        "ingestion": _serialize_ingestion(ing),
        "quality_report": qr["report"] if qr else None,
    }


@app.get("/api/ingestions/{ingestion_id}/lineage")
def api_get_lineage(ingestion_id: str) -> Dict[str, Any]:
    art = get_lineage_artifact(ingestion_id)
    if not art:
        raise HTTPException(status_code=404, detail="not found")
    return art


@app.post("/api/ingestions/{ingestion_id}/replay")
def api_replay(ingestion_id: str, request: Request) -> Dict[str, Any]:
    # Replay creates a NEW ingestion record referencing the same raw artifact.
    new_id = str(create_replay_ingestion(ingestion_id))
    enq = enqueue_ingestion(new_id, request_base_url=str(request.base_url))

    # Best-effort audit trail
    try:
        insert_audit_event(
            event_type="ingestion.replay_requested",
            actor=_actor_from_request(request) or "api",
            ingestion_id=new_id,
            details={"replay_of": ingestion_id},
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "action": "replay", "ingestion_id": new_id})

    return {"ok": True, "replay_of": ingestion_id, "ingestion_id": new_id, "job_backend": enq.backend, "job_id": enq.id}


@app.get("/api/ingestions/{ingestion_id}/preview")
def api_preview(ingestion_id: str, limit: int = 10) -> Dict[str, Any]:
    ing = get_ingestion(ingestion_id)
    if not ing:
        raise HTTPException(status_code=404, detail="not found")

    dataset = normalize_dataset_name(str(ing["dataset"]))
    table_exists = curated_table_exists(dataset)
    rows = []
    if table_exists:
        rows = sample_curated_for_ingestion(dataset, ingestion_id, limit=limit)

    return {
        "ingestion_id": ingestion_id,
        "dataset": dataset,
        "table_exists": table_exists,
        "rows": rows,
        "limit": limit,
    }


# -----------------------------
# Dataset endpoints
# -----------------------------


@app.get("/api/datasets")
def api_list_datasets(limit: int = 100) -> Dict[str, Any]:
    """List datasets known to the platform.

    Sources:
    - Contracts on disk (CONTRACTS_DIR)
    - Datasets observed in the ingestions table (Postgres)

    The UI uses this to power the dataset explorer.
    """

    limit = max(1, min(int(limit), 200))

    # Contracts on disk
    contract_dir = Path(settings.contracts_dir)
    contract_datasets: Dict[str, Dict[str, Any]] = {}
    if contract_dir.exists():
        for p in sorted(contract_dir.glob("*.yaml")):
            ds = normalize_dataset_name(p.stem)
            try:
                meta = load_contract_with_meta(ds)
                contract_datasets[ds] = {
                    "dataset": ds,
                    "has_contract": True,
                    "contract_sha256": meta.sha256,
                    "contract_description": meta.contract.description,
                    "primary_key": meta.contract.primary_key,
                    "drift_policy": meta.contract.drift_policy,
                }
            except Exception:
                # Best-effort: a malformed contract shouldn't break the whole listing.
                contract_datasets[ds] = {"dataset": ds, "has_contract": True}

    # DB summaries (may be empty on first boot)
    summaries = list_dataset_summaries(limit=limit)
    summary_map = {str(s.get("dataset")): s for s in summaries if s.get("dataset")}

    dataset_names = sorted(set(contract_datasets.keys()) | set(summary_map.keys()))
    items: list[Dict[str, Any]] = []

    for ds in dataset_names:
        base: Dict[str, Any] = {"dataset": ds}
        base.update(contract_datasets.get(ds, {"has_contract": False}))

        s = summary_map.get(ds, {})
        base["ingestion_count"] = int(s.get("ingestion_count") or 0)
        base["last_received_at"] = s.get("last_received_at")
        base["last_processed_at"] = s.get("last_processed_at")
        base["counts"] = {
            "received": int(s.get("received_count") or 0),
            "processing": int(s.get("processing_count") or 0),
            "success": int(s.get("success_count") or 0),
            "failed": int(s.get("failed_count") or 0),
        }

        base["curated_table_exists"] = curated_table_exists(ds)

        # Latest schema hash (if any)
        try:
            hist = list_schema_history(ds, limit=1)
            if hist:
                base["latest_schema_hash"] = hist[0].get("schema_hash")
                base["schema_last_seen_at"] = hist[0].get("last_seen_at")
            else:
                base["latest_schema_hash"] = None
                base["schema_last_seen_at"] = None
        except Exception:
            base["latest_schema_hash"] = None
            base["schema_last_seen_at"] = None

        items.append(base)

    return {"items": items}


@app.get("/api/datasets/{dataset}/contract")
def api_get_contract(dataset: str) -> Dict[str, Any]:
    """Fetch the dataset contract (YAML) + parsed metadata."""

    dataset = normalize_dataset_name(dataset)
    try:
        meta = load_contract_with_meta(dataset)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="contract not found")

    try:
        raw_yaml = Path(meta.path).read_text(encoding="utf-8")
    except Exception:
        raw_yaml = ""

    c = meta.contract

    return {
        "dataset": dataset,
        "contract": {
            "sha256": meta.sha256,
            "filename": os.path.basename(meta.path),
            "description": c.description,
            "primary_key": c.primary_key,
            "drift_policy": c.drift_policy,
            "quality": c.quality,
            "columns": c.columns,
            "raw_yaml": raw_yaml,
        },
    }


@app.post("/api/contracts/validate")
def api_validate_contract(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Validate a contract YAML payload (does not write anything)."""

    raw_yaml = str(payload.get("raw_yaml") or payload.get("yaml") or "")
    try:
        contract = parse_contract_yaml(raw_yaml)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "contract": {
            "dataset": contract.dataset,
            "description": contract.description,
            "primary_key": contract.primary_key,
            "drift_policy": contract.drift_policy,
            "quality": contract.quality,
            "columns": contract.columns,
        },
    }


@app.put("/api/datasets/{dataset}/contract")
def api_put_contract(dataset: str, request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Update a dataset contract (write YAML file).

    Disabled by default. Enable with:
      ENABLE_CONTRACT_WRITE=true

    This endpoint requires internal auth (TASK_TOKEN or Cloud Run IAM).
    """

    dataset = normalize_dataset_name(dataset)

    if not settings.enable_contract_write:
        raise HTTPException(status_code=404, detail="contract write disabled")

    _require_internal_auth(request)

    raw_yaml = str(payload.get("raw_yaml") or payload.get("yaml") or "")
    try:
        contract = parse_contract_yaml(raw_yaml)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if contract.dataset != dataset:
        raise HTTPException(
            status_code=400, detail=f"contract dataset mismatch: expected {dataset!r}, got {contract.dataset!r}"
        )

    contracts_dir = Path(settings.contracts_dir).resolve()
    try:
        contracts_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to create contracts dir: {e}")

    out_path = (contracts_dir / f"{dataset}.yaml").resolve()
    # Defense-in-depth: ensure we stay within contracts_dir
    if contracts_dir not in out_path.parents:
        raise HTTPException(status_code=400, detail="invalid contract path")

    try:
        out_path.write_text(raw_yaml, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to write contract file: {e}")

    meta = load_contract_with_meta(dataset)

    # Best-effort audit trail
    try:
        insert_audit_event(
            event_type="contract.updated",
            actor=_actor_from_request(request) or "api",
            dataset=dataset,
            details={"sha256": meta.sha256, "filename": os.path.basename(meta.path)},
        )
    except Exception as e:
        logger.warning("audit insert failed", extra={"error": str(e), "action": "contract.updated", "dataset": dataset})

    c = meta.contract
    try:
        raw_yaml_saved = Path(meta.path).read_text(encoding="utf-8")
    except Exception:
        raw_yaml_saved = ""

    return {
        "dataset": dataset,
        "contract": {
            "sha256": meta.sha256,
            "filename": os.path.basename(meta.path),
            "description": c.description,
            "primary_key": c.primary_key,
            "drift_policy": c.drift_policy,
            "quality": c.quality,
            "columns": c.columns,
            "raw_yaml": raw_yaml_saved,
        },
    }


@app.get("/api/datasets/{dataset}/marts")
def api_list_marts(dataset: str) -> Dict[str, Any]:
    dataset = normalize_dataset_name(dataset)
    marts = list_dataset_marts(dataset)

    # Mark which views exist (curated table may not exist yet)
    for m in marts:
        v = m.get("view") or ""
        m["exists"] = bool(v and view_exists(v))

    return {"dataset": dataset, "items": marts}


@app.get("/api/datasets/{dataset}/marts/{mart}")
def api_get_mart(dataset: str, mart: str, limit: int = 200) -> Dict[str, Any]:
    dataset = normalize_dataset_name(dataset)
    mart = str(mart or "").strip().lower()

    available = list_dataset_marts(dataset)
    entry = next((m for m in available if m.get("name") == mart), None)
    if not entry:
        raise HTTPException(status_code=404, detail="mart not found")

    view = str(entry.get("view") or "")
    if not view or not view_exists(view):
        raise HTTPException(status_code=404, detail="mart view not available yet (ingest data first)")

    rows = sample_view(view, limit=limit)

    return {"dataset": dataset, "mart": mart, "view": view, "rows": rows, "limit": limit}


@app.get("/api/datasets/{dataset}/curated/sample")
def api_curated_sample(dataset: str, limit: int = 20) -> Dict[str, Any]:
    dataset = normalize_dataset_name(dataset)
    exists = curated_table_exists(dataset)
    rows = sample_curated(dataset, limit=limit) if exists else []
    return {"rows": rows, "limit": limit, "table_exists": exists}


@app.get("/api/datasets/{dataset}/schemas")
def api_schema_history(dataset: str, limit: int = 20) -> Dict[str, Any]:
    dataset = normalize_dataset_name(dataset)
    items = list_schema_history(dataset, limit=limit)
    return {"dataset": dataset, "items": items}


@app.get("/api/data_products")
def api_data_products(limit_datasets: int = 200) -> Dict[str, Any]:
    """List data products (published marts) across all datasets.

    This is an opinionated "catalog" endpoint for the UI:
    - show what's available
    - expose stable API paths for consumption
    """

    limit_datasets = max(1, min(int(limit_datasets), 500))

    # Reuse dataset discovery logic from /api/datasets without duplicating the response format.
    # We intentionally keep this lightweight: derive datasets from contracts + DB summary.
    contract_dir = Path(settings.contracts_dir)
    ds_from_contracts: set[str] = set()
    if contract_dir.exists():
        for p in sorted(contract_dir.glob("*.yaml")):
            try:
                ds_from_contracts.add(normalize_dataset_name(p.stem))
            except Exception:
                continue

    summaries = list_dataset_summaries(limit=limit_datasets)
    ds_from_db: set[str] = set()
    for s in summaries:
        ds = s.get("dataset")
        if ds:
            try:
                ds_from_db.add(normalize_dataset_name(str(ds)))
            except Exception:
                continue

    datasets = sorted(ds_from_contracts | ds_from_db)[:limit_datasets]

    products: list[Dict[str, Any]] = []
    for ds in datasets:
        contract_sha256: Optional[str] = None
        contract_version: Optional[str] = None
        try:
            res = load_contract_with_meta(ds)
            contract_sha256 = res.sha256
            contract_version = res.sha256[:8]
        except Exception:
            contract_sha256 = None
            contract_version = None
        marts = list_dataset_marts(ds)
        for m in marts:
            mart_name = str(m.get("name") or "")
            view = str(m.get("view") or "")
            exists = bool(view and view_exists(view))
            products.append(
                {
                    "dataset": ds,
                    "name": mart_name,
                    "kind": str(m.get("kind") or "mart"),
                    "description": str(m.get("description") or ""),
                    "view": view,
                    "exists": exists,
                    "endpoint": f"/api/datasets/{ds}/marts/{mart_name}",
                    "version": contract_version,
                    "contract_sha256": contract_sha256,
                }
            )

    return {"items": products, "dataset_count": len(datasets), "count": len(products)}


# -----------------------------
# Demo endpoint
# -----------------------------


@app.post("/api/demo/seed/parcels", include_in_schema=False)
def seed_parcels(request: Request, limit: int = 50, per_ingestion_max: int = 15) -> Dict[str, Any]:
    """Seed a demo dataset by enqueuing multiple ingestions.

    Uses the packaged sample file in `data/samples/` by default.
    """

    if not settings.enable_demo_endpoints:
        raise HTTPException(status_code=404, detail="demo endpoints disabled")

    # Prefer a user-provided file in INCOMING_DIR (handy for quick experimentation).
    candidates = [
        Path(settings.incoming_dir) / "parcels_baseline.xlsx",
        Path(__file__).resolve().parent.parent / "data" / "samples" / "parcels_baseline.xlsx",
    ]

    src = next((p for p in candidates if p.exists()), None)
    if not src:
        raise HTTPException(
            status_code=404, detail="missing parcels_baseline.xlsx (checked INCOMING_DIR and packaged samples)"
        )

    ingestions = []
    total_rows = 0

    df = pd.read_excel(src)
    n = min(limit, len(df))
    df = df.head(n)

    chunks = [df[i : i + per_ingestion_max] for i in range(0, len(df), per_ingestion_max)]
    seed_id = uuid.uuid4().hex[:8]

    work_dir = Path("/tmp") / f"eventpulse_seed_{seed_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        for idx, chunk in enumerate(chunks):
            out_path = work_dir / f"parcels_seed_{seed_id}_{idx}.xlsx"
            chunk.to_excel(out_path, index=False)
            ingestion_id = create_ingestion_record("parcels", f"seed:{seed_id}", str(out_path))
            enq = enqueue_ingestion(ingestion_id, request_base_url=str(request.base_url))
            ingestions.append({"ingestion_id": ingestion_id, "job_id": enq.id, "rows": len(chunk)})
            total_rows += len(chunk)

        return {
            "ok": True,
            "rows": total_rows,
            "seed_id": seed_id,
            "per_ingestion_max": per_ingestion_max,
            "ingestions": ingestions,
        }

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# -----------------------------
# Static UI
# -----------------------------


# Serve built frontend (if present). In local dev, the API container builds it.
_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.exists():
    app.mount("/", SPAStaticFiles(directory=str(_dist), html=True), name="static")


# Helpers


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    # Minimal parsing; keep separate from jobs.py to avoid importing job module in API import path.
    if not uri.startswith("gs://"):
        raise ValueError("not a gs:// uri")
    rest = uri[len("gs://") :]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        raise ValueError("invalid gs:// uri")
    bucket, object_name = parts[0], parts[1]
    if not bucket or not object_name:
        raise ValueError("invalid gs:// uri")
    return bucket, object_name


def _archive_incoming_file(src: Path, *, ingestion_id: str, dataset: str) -> None:
    archive_root = Path(settings.archive_dir) / dataset
    archive_root.mkdir(parents=True, exist_ok=True)

    # Unique name avoids collisions and makes it easy to trace.
    dest = archive_root / f"{ingestion_id}__{src.name}"

    try:
        shutil.move(str(src), str(dest))
    except Exception:
        # Best-effort: do not fail ingestion if archiving fails.
        pass


def _serialize_ingestion(ing: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize ingestion record for the UI."""

    status_raw = str(ing.get("status") or "").upper()
    if status_raw == "RECEIVED":
        status = "received"
    elif status_raw == "PROCESSING":
        status = "processing"
    elif status_raw == "LOADED":
        status = "success"
    elif status_raw.startswith("FAILED"):
        status = "failed"
    else:
        status = status_raw.lower() or "unknown"

    def _iso(v: Any) -> Optional[str]:
        return v.isoformat() if hasattr(v, "isoformat") and v is not None else None

    return {
        "id": str(ing.get("id")),
        "dataset": ing.get("dataset"),
        "source": ing.get("source"),
        "filename": ing.get("filename"),
        "file_ext": ing.get("file_ext"),
        "sha256": ing.get("sha256"),
        "raw_path": ing.get("raw_path"),
        "raw_generation": ing.get("raw_generation"),
        "received_at": _iso(ing.get("received_at")),
        "processing_started_at": _iso(ing.get("processing_started_at")),
        "processing_heartbeat_at": _iso(ing.get("processing_heartbeat_at")),
        "processing_attempts": int(ing.get("processing_attempts") or 0),
        "status": status,
        "error": ing.get("error"),
        "processed_at": _iso(ing.get("processed_at")),
    }
