#!/usr/bin/env python3
"""Reclaim ingestions stuck in PROCESSING.

This is primarily useful for local development and debugging.

In production on Cloud Run, prefer calling the internal endpoint:
  POST /internal/admin/reclaim_stuck

which can be protected via TASK_AUTH_MODE (token or IAM).
"""

from __future__ import annotations

import argparse
import json

from eventpulse.config import settings
from eventpulse.db import init_db, reclaim_stuck_ingestions
from eventpulse.queueing import enqueue_ingestion


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclaim stuck PROCESSING ingestions and optionally re-enqueue them.")
    parser.add_argument(
        "--older-than-seconds",
        type=int,
        default=settings.processing_ttl_seconds,
        help="Consider PROCESSING rows older than this threshold as stuck.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.reclaim_max_per_run,
        help="Maximum number of ingestions to reclaim in one run.",
    )
    parser.add_argument(
        "--reenqueue",
        action="store_true",
        default=True,
        help="Re-enqueue reclaimed ingestions (default: true).",
    )
    parser.add_argument(
        "--no-reenqueue",
        dest="reenqueue",
        action="store_false",
        help="Do not re-enqueue reclaimed ingestions.",
    )
    parser.add_argument(
        "--task-base-url",
        default="",
        help="Base URL used for Cloud Tasks target (only needed when QUEUE_BACKEND=cloud_tasks and TASK_TARGET_BASE_URL isn't set).",
    )

    args = parser.parse_args()

    init_db()

    reclaimed = reclaim_stuck_ingestions(older_than_seconds=args.older_than_seconds, limit=args.limit)

    requeued: list[dict[str, str]] = []
    if args.reenqueue and reclaimed:
        base_url = args.task_base_url or settings.task_target_base_url
        for ing_id in reclaimed:
            try:
                enq = enqueue_ingestion(ing_id, request_base_url=base_url or None)
                requeued.append({"ingestion_id": ing_id, "backend": enq.backend, "job_id": enq.id})
            except Exception as e:
                requeued.append({"ingestion_id": ing_id, "error": str(e)})

    print(
        json.dumps(
            {
                "ok": True,
                "older_than_seconds": args.older_than_seconds,
                "limit": args.limit,
                "reclaimed": reclaimed,
                "reenqueue": args.reenqueue,
                "reenqueued": requeued,
            },
            indent=2,
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
