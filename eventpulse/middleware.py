from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response

from .logging_setup import parse_cloud_trace_context, request_id_var, span_id_var, trace_var


async def request_context_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    """Attach request_id + trace correlation to contextvars.

    - request_id: X-Request-ID (if present) else uuid4
    - trace/span: X-Cloud-Trace-Context (Cloud Run)

    Adds `X-Request-ID` to response for client correlation.
    """

    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token_rid = request_id_var.set(rid)

    trace_header = request.headers.get("X-Cloud-Trace-Context")
    ct = parse_cloud_trace_context(trace_header or "") if trace_header else None
    token_trace = None
    token_span = None
    if ct:
        token_trace = trace_var.set(ct.trace_id)
        if ct.span_id:
            token_span = span_id_var.set(ct.span_id)

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token_rid)
        if token_trace is not None:
            trace_var.reset(token_trace)
        if token_span is not None:
            span_id_var.reset(token_span)
