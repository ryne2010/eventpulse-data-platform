from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd

from eventpulse.loaders.postgres import _to_db_scalar


def test_to_db_scalar_handles_missing_values() -> None:
    assert _to_db_scalar(None) is None
    assert _to_db_scalar(np.nan) is None
    assert _to_db_scalar(float("nan")) is None
    assert _to_db_scalar(pd.NA) is None
    assert _to_db_scalar(pd.NaT) is None


def test_to_db_scalar_converts_numpy_and_timestamps() -> None:
    assert _to_db_scalar(np.int64(42)) == 42
    ts = pd.Timestamp("2026-01-01T12:00:00Z")
    py_dt = _to_db_scalar(ts)
    assert py_dt.year == 2026
    assert py_dt.tzinfo == timezone.utc
