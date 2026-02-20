"""Naming and validation helpers.

This module centralizes rules for user-controlled identifiers that become:
- directory names (raw landing zone)
- contract filenames
- database identifiers (curated_<dataset>)

Keeping these rules strict prevents:
- path traversal
- surprising casing issues (Postgres lowercases unquoted identifiers)
- SQL injection via dynamically constructed identifiers

Dataset naming convention (demo posture):
- lowercase letters, numbers, underscore
- must start with a letter

Examples: parcels, recorder_sales, real_estate_2026
"""

from __future__ import annotations

import re

_DATASET_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def normalize_dataset_name(dataset: str) -> str:
    """Normalize and validate a dataset name.

    We accept mixed-case inputs but normalize to lowercase. If the normalized
    value doesn't match our strict pattern, raise ValueError.
    """

    d = (dataset or "").strip().lower()
    if not d:
        raise ValueError("Dataset is required")
    if not _DATASET_RE.fullmatch(d):
        raise ValueError(
            "Invalid dataset name. Use lowercase letters/numbers/underscore, start with a letter, max 63 chars. "
            f"Got: {dataset!r}"
        )
    return d
