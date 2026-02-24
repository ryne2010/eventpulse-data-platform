from __future__ import annotations

from eventpulse.loaders.postgres import _clamp_sample_limit


def test_clamp_sample_limit_bounds() -> None:
    assert _clamp_sample_limit(-100) == 1
    assert _clamp_sample_limit(25) == 25
    assert _clamp_sample_limit(10**30) == 2000
