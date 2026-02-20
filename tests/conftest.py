"""Pytest configuration.

The EventPulse repo is intentionally *app-first* (not published as a Python
package). For tests we add the repo root to sys.path so `import eventpulse`
works without an editable install.

If/when this repo is converted into a distributable package, this can be
removed.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
