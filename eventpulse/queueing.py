from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import normalize_task_auth_mode, settings
from .gcp_rest import cloud_tasks_create_http_task
from .jobs import process_ingestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnqueueResult:
    backend: str
    id: str
    extra: Dict[str, Any]


_redis_queue: Any = None


def _get_redis_queue() -> Any:
    global _redis_queue
    if _redis_queue is None:
        # Lazy import keeps Cloud Run images smaller when not using Redis.
        from redis import Redis
        from rq import Queue

        redis_conn = Redis.from_url(settings.redis_url)
        _redis_queue = Queue("eventpulse", connection=redis_conn)
    return _redis_queue


def enqueue_ingestion(ingestion_id: str, *, request_base_url: Optional[str] = None) -> EnqueueResult:
    backend = settings.queue_backend

    if backend == "inline":
        logger.info("Processing ingestion inline", extra={"ingestion_id": ingestion_id})
        result = process_ingestion(ingestion_id)
        # Inline path returns a pseudo-id for the "job".
        return EnqueueResult(backend="inline", id=ingestion_id, extra={"result": result})

    if backend == "cloud_tasks":
        if not settings.task_target_base_url:
            # Allow fallback to the current request base URL (useful behind proxies/custom domains).
            if request_base_url:
                base = request_base_url.rstrip("/")
            else:
                raise ValueError("TASK_TARGET_BASE_URL must be set when QUEUE_BACKEND=cloud_tasks")
        else:
            base = settings.task_target_base_url.rstrip("/")

        if not settings.cloud_tasks_project or not settings.cloud_tasks_location or not settings.cloud_tasks_queue:
            raise ValueError("CLOUD_TASKS_PROJECT, CLOUD_TASKS_LOCATION, CLOUD_TASKS_QUEUE must be set")

        auth_mode = normalize_task_auth_mode(settings.task_auth_mode)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        oidc_email: Optional[str] = None
        if auth_mode == "token":
            if not settings.task_token:
                raise ValueError("TASK_TOKEN must be set when TASK_AUTH_MODE=token")
            headers["X-Task-Token"] = settings.task_token
        else:
            if not settings.task_oidc_service_account_email:
                raise ValueError("TASK_OIDC_SERVICE_ACCOUNT_EMAIL must be set when TASK_AUTH_MODE=iam")
            oidc_email = settings.task_oidc_service_account_email

        target_url = f"{base}/internal/tasks/process_ingestion"

        task_name = cloud_tasks_create_http_task(
            project=settings.cloud_tasks_project,
            location=settings.cloud_tasks_location,
            queue=settings.cloud_tasks_queue,
            url=target_url,
            body_json={"ingestion_id": ingestion_id},
            headers=headers,
            oidc_service_account_email=oidc_email,
            dispatch_deadline_seconds=settings.cloud_tasks_dispatch_deadline_seconds,
        )

        return EnqueueResult(backend="cloud_tasks", id=task_name, extra={"target_url": target_url})

    # default: redis
    q = _get_redis_queue()
    job = q.enqueue(process_ingestion, ingestion_id)
    return EnqueueResult(backend="redis", id=job.id, extra={})
