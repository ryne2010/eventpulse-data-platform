from __future__ import annotations

from pathlib import Path

import eventpulse.db as db


def test_failed_like_clauses_escape_percent_for_psycopg2() -> None:
    """Queries with parameters must escape LIKE percent as %% for psycopg2."""

    source = Path(db.__file__).read_text(encoding="utf-8")
    assert "LIKE 'FAILED%%'" in source
    assert "LIKE 'FAILED%'" not in source
