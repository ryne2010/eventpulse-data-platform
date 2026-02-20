from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class Settings:
    # -----------------
    # App
    # -----------------
    app_env: str = os.getenv("APP_ENV", "local")

    # -----------------
    # Core
    # -----------------
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:eventpulse@localhost:5432/eventpulse")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # -----------------
    # Storage
    # -----------------
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local").lower()  # local|gcs

    # Local filesystem paths (Docker Compose lane)
    raw_data_dir: str = os.getenv("RAW_DATA_DIR", "/data/raw")
    contracts_dir: str = os.getenv("CONTRACTS_DIR", "/data/contracts")
    incoming_dir: str = os.getenv("INCOMING_DIR", "/data/incoming")
    archive_dir: str = os.getenv("ARCHIVE_DIR", "/data/archive")

    # GCS raw landing zone (Cloud Run lane)
    raw_gcs_bucket: str = os.getenv("RAW_GCS_BUCKET", "")
    raw_gcs_prefix: str = os.getenv("RAW_GCS_PREFIX", "raw")

    # Direct-to-GCS upload helpers (Cloud Run lane)
    # IMPORTANT: only enable this on a *private* service (Cloud Run IAM required),
    # otherwise anyone could mint signed URLs to your bucket.
    enable_signed_urls: bool = _truthy(os.getenv("ENABLE_SIGNED_URLS", "false"))
    signed_url_expires_seconds: int = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "900"))
    require_signed_url_sha256: bool = _truthy(os.getenv("REQUIRE_SIGNED_URL_SHA256", "true"))

    # -----------------
    # Edge media uploads (optional)
    # -----------------
    # Optional signed-URL flow for edge devices to upload photos/videos directly to GCS.
    # This is intentionally separate from ingestion files: media objects are not processed
    # by the data-quality pipeline unless you build a dedicated processor.
    enable_edge_media: bool = _truthy(os.getenv("ENABLE_EDGE_MEDIA", "false"))
    edge_media_gcs_bucket: str = os.getenv("EDGE_MEDIA_GCS_BUCKET", "")
    edge_media_gcs_prefix: str = os.getenv("EDGE_MEDIA_GCS_PREFIX", "media")
    edge_media_signed_url_expires_seconds: int = int(
        os.getenv("EDGE_MEDIA_SIGNED_URL_EXPIRES_SECONDS", os.getenv("SIGNED_URL_EXPIRES_SECONDS", "900"))
    )
    edge_media_allowed_exts: List[str] = _split_csv(
        os.getenv("EDGE_MEDIA_ALLOWED_EXTS", ".jpg,.jpeg,.png,.mp4,.webm")
    )

    # Event-driven ingestion from GCS object finalize events (Cloud Run lane)
    enable_gcs_event_ingestion: bool = _truthy(os.getenv("ENABLE_GCS_EVENT_INGESTION", "false"))

    # -----------------
    # Queue / async
    # -----------------
    queue_backend: str = os.getenv("QUEUE_BACKEND", "redis").lower()  # redis|inline|cloud_tasks

    # Cloud Tasks config (Cloud Run lane)
    cloud_tasks_project: str = os.getenv("CLOUD_TASKS_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    cloud_tasks_location: str = os.getenv("CLOUD_TASKS_LOCATION", os.getenv("REGION", ""))
    cloud_tasks_queue: str = os.getenv("CLOUD_TASKS_QUEUE", "")

    # Public base URL for the task target (e.g., https://service-xyz.a.run.app)
    task_target_base_url: str = os.getenv("TASK_TARGET_BASE_URL", "")

    # Cloud Tasks dispatch deadline (must be <= Cloud Run request timeout).
    cloud_tasks_dispatch_deadline_seconds: int = int(os.getenv("CLOUD_TASKS_DISPATCH_DEADLINE_SECONDS", "900"))

    # Shared-secret header used to protect internal task endpoints.
    task_token: str = os.getenv("TASK_TOKEN", "")

    # Internal auth mode for task/admin endpoints.
    #
    # - token: require X-Task-Token header
    # - iam/oidc: rely on Cloud Run IAM (tasks/scheduler call with OIDC tokens)
    task_auth_mode: str = os.getenv("TASK_AUTH_MODE", "token").lower()
    task_oidc_service_account_email: str = os.getenv("TASK_OIDC_SERVICE_ACCOUNT_EMAIL", "")

    # -----------------
    # Curated destination
    # -----------------
    curated_backend: str = os.getenv("CURATED_BACKEND", "postgres").lower()  # postgres|bigquery

    # BigQuery (optional)
    bigquery_project: str = os.getenv("BIGQUERY_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    bigquery_dataset: str = os.getenv("BIGQUERY_DATASET", "eventpulse")
    bigquery_location: str = os.getenv("BIGQUERY_LOCATION", os.getenv("REGION", "US"))

    # -----------------
    # Ingestion controls
    # -----------------
    # Optional auth for the public ingest endpoint (/api/ingest/upload).
    #
    # Why this exists:
    # - In production, you may keep the ingest service public (edge devices, partners)
    #   but still want a shared-secret to prevent drive-by uploads.
    # - This is intentionally *separate* from TASK_TOKEN, which protects internal
    #   admin/task endpoints.
    #
    # Modes:
    # - none:  no auth required
    # - token: require X-Ingest-Token header
    ingest_auth_mode: str = os.getenv("INGEST_AUTH_MODE", "none").lower()
    ingest_token: str = os.getenv("INGEST_TOKEN", "")

    # -----------------
    # Edge device auth (field devices)
    # -----------------
    # Field devices (ex: Raspberry Pi over 5G) typically cannot use Cloud Run IAM.
    # We support a per-device token model with server-side revocation and rotation.
    #
    # Modes:
    # - none:  no auth required (local demo only)
    # - token: require X-Device-Id + X-Device-Token
    _edge_auth_default: str = "none" if os.getenv("APP_ENV", "local").lower() == "local" else "token"
    edge_auth_mode: str = os.getenv("EDGE_AUTH_MODE", _edge_auth_default).lower()

    # Optional bootstrap enrollment token.
    #
    # Field reality: manually provisioning unique tokens onto many devices slows down
    # deployments. If EDGE_ENROLL_TOKEN is set, edge devices may POST to /api/edge/enroll
    # with a shared enrollment token to mint/rotate their *per-device* token.
    #
    # Security note: treat this like a fleet secret. Keep it in Secret Manager and rotate
    # if you suspect compromise.
    edge_enroll_token: str = os.getenv("EDGE_ENROLL_TOKEN", "")

    # Allow-list which datasets devices can upload into (comma-separated).
    # Default keeps the demo tight: only edge_telemetry.
    edge_allowed_datasets: Tuple[str, ...] = tuple(_split_csv(os.getenv("EDGE_ALLOWED_DATASETS", "edge_telemetry")))

    # When true, expose device-authenticated signed URL helpers under /api/edge/.
    # This is the recommended production path on Cloud Run (avoids request size limits).
    enable_edge_signed_urls: bool = _truthy(os.getenv("ENABLE_EDGE_SIGNED_URLS", "false"))

    # Field ops tuning: how long until a device is considered "offline".
    #
    # This value is used when building the Postgres mart view:
    #   marts_edge_telemetry_device_status
    #
    # Default (10 minutes) is intentionally conservative.
    edge_offline_threshold_seconds: int = int(os.getenv("EDGE_OFFLINE_THRESHOLD_SECONDS", "600"))

    drift_policy_default: str = os.getenv("DRIFT_POLICY_DEFAULT", "warn").lower()  # warn|fail|allow
    max_file_mb: int = int(os.getenv("MAX_FILE_MB", "50"))
    allowed_file_exts: Tuple[str, ...] = tuple(_split_csv(os.getenv("ALLOWED_FILE_EXTS", ".csv,.xlsx,.xls")))

    # Allow local ingest-by-path endpoint (handy for Docker Compose).
    enable_ingest_from_path: bool = _truthy(os.getenv("ENABLE_INGEST_FROM_PATH", "true"))

    # Allow updating contracts via API (disabled by default; intended for local dev/demo).
    enable_contract_write: bool = _truthy(os.getenv("ENABLE_CONTRACT_WRITE", "false"))

    # Allow listing INCOMING_DIR via API (disabled by default; local dev convenience).
    enable_incoming_list: bool = _truthy(os.getenv("ENABLE_INCOMING_LIST", "false"))

    # Demo endpoints (seed helpers). Default: enabled for local, disabled elsewhere.
    _demo_default: str = "true" if os.getenv("APP_ENV", "local").lower() == "local" else "false"
    enable_demo_endpoints: bool = _truthy(os.getenv("ENABLE_DEMO_ENDPOINTS", _demo_default))

    # -----------------
    # Processing hardening
    # -----------------
    # If a worker/Cloud Run instance dies after marking an ingestion PROCESSING,
    # retries can be skipped. A reclaimer can recover stuck ingestions.
    processing_ttl_seconds: int = int(os.getenv("PROCESSING_TTL_SECONDS", "900"))
    reclaim_max_per_run: int = int(os.getenv("RECLAIM_MAX_PER_RUN", "50"))

    # Cap how many times a single ingestion can be claimed for processing.
    #
    # This is a safety valve for pathological inputs that always fail (e.g.,
    # corrupt files) so a queue can't churn forever.
    #
    # Note: Cloud Tasks has its own retry limits; this applies to the *platform*
    # claim counter stored in Postgres.
    max_processing_attempts: int = max(1, int(os.getenv("MAX_PROCESSING_ATTEMPTS", "5")))

    # -----------------
    # Watcher
    # -----------------
    watch_poll_seconds: int = int(os.getenv("WATCH_POLL_SECONDS", "3"))

    # -----------------
    # Logging
    # -----------------
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format: str = os.getenv("LOG_FORMAT", "json").lower()  # json|console


settings = Settings()


def normalize_task_auth_mode(mode: str) -> str:
    """Normalize task auth mode.

    Accept a few aliases so environment config is forgiving.

    Modes:
    - none:  no auth required (local/dev only)
    - token: require X-Task-Token
    - iam:   rely on Cloud Run / service-to-service IAM (OIDC)
    """

    m = (mode or "").strip().lower()
    if m in ("none", "public", "open"):
        return "none"
    if m in ("iam", "oidc"):
        return "iam"
    return "token"


def normalize_ingest_auth_mode(mode: str) -> str:
    """Normalize ingest auth mode."""

    m = (mode or "").strip().lower()
    if m in ("token", "shared_secret", "shared-secret"):
        return "token"
    return "none"


def normalize_edge_auth_mode(mode: str) -> str:
    """Normalize edge device auth mode."""

    m = (mode or "").strip().lower()
    if m in ("token", "device", "device_token", "device-token", "per_device", "per-device"):
        return "token"
    return "none"
