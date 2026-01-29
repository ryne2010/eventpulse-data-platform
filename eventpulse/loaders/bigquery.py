"""Optional BigQuery loader (cloud path).

This reference implementation keeps the local-first default (Postgres).
If you want to load curated data to BigQuery, implement:
- authentication (ADC / service account)
- dataset/table creation
- load jobs (streaming inserts or load from GCS)

We intentionally keep this file as a stub to avoid forcing BigQuery dependencies
for local development.

See docs/gcp_deploy.md for recommended cloud mapping.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..contracts import DatasetContract


class BigQueryLoaderNotConfigured(RuntimeError):
    pass


def upsert_curated_bigquery(*args: Any, **kwargs: Any) -> int:
    raise BigQueryLoaderNotConfigured(
        "BigQuery loader is not configured in this local-first repo. "
        "See docs/gcp_deploy.md to wire BigQuery loading."
    )
