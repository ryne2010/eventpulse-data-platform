"""Logging configuration.

Goals:
- Structured JSON logs by default (Cloud Logging friendly)
- Automatically include request_id + trace correlation when available
- Minimal dependencies (stdlib only)

Cloud Run log correlation:
- Cloud Run forwards `X-Cloud-Trace-Context`.
- Cloud Logging links traces when log entries include:
  - "logging.googleapis.com/trace": "projects/<PROJECT_ID>/traces/<TRACE_ID>"

We also propagate request IDs:
- Use inbound `X-Request-ID` when present.
- Otherwise generate a UUID4.

See: docs/OBSERVABILITY.md
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Context vars set by middleware
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
trace_var: ContextVar[Optional[str]] = ContextVar("trace", default=None)
span_id_var: ContextVar[Optional[str]] = ContextVar("span_id", default=None)


@dataclass(frozen=True)
class CloudTraceContext:
    trace_id: str
    span_id: Optional[str] = None

    def logging_trace_field(self, project_id: str) -> str:
        return f"projects/{project_id}/traces/{self.trace_id}"


def parse_cloud_trace_context(header_value: str) -> Optional[CloudTraceContext]:
    """Parse X-Cloud-Trace-Context header.

    Format: TRACE_ID/SPAN_ID;o=TRACE_TRUE
    """

    if not header_value:
        return None
    # Keep it permissive: split on ';' first.
    left = header_value.split(";", 1)[0].strip()
    if not left:
        return None
    if "/" in left:
        trace_id, span_id_raw = left.split("/", 1)
        trace_id = trace_id.strip()
        span_id = span_id_raw.strip() or None
    else:
        trace_id = left.strip()
        span_id = None

    # Basic sanity: trace_id is hex.
    if not trace_id or any(c not in "0123456789abcdefABCDEF" for c in trace_id):
        return None
    return CloudTraceContext(trace_id=trace_id, span_id=span_id)


class _ContextFilter(logging.Filter):
    def __init__(self, project_id: str):
        super().__init__()
        self._project_id = project_id

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        rid = request_id_var.get()
        if rid:
            setattr(record, "request_id", rid)

        trace_id = trace_var.get()
        if trace_id and self._project_id:
            setattr(record, "gcp_trace", f"projects/{self._project_id}/traces/{trace_id}")

        span_id = span_id_var.get()
        if span_id:
            setattr(record, "gcp_span_id", span_id)

        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Common structured fields (set by filter / extra)
        for key, out_key in [
            ("request_id", "request_id"),
            ("ingestion_id", "ingestion_id"),
            ("dataset", "dataset"),
            ("gcp_trace", "logging.googleapis.com/trace"),
            ("gcp_span_id", "logging.googleapis.com/spanId"),
        ]:
            v = getattr(record, key, None)
            if v is not None:
                payload[out_key] = v

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging(*, log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure root logging.

    Idempotent: safe to call multiple times.
    """

    level = getattr(logging, (log_level or "INFO").upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicate logs when Uvicorn config runs.
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    if (log_format or "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT", ""))
    handler.addFilter(_ContextFilter(project_id=project_id))

    root.addHandler(handler)

    # Quiet some noisy libs (keep errors).
    logging.getLogger("google.auth").setLevel(max(level, logging.WARNING))
