import os
import time
from pathlib import Path
from typing import Set

import requests

from eventpulse.config import settings


def main() -> None:
    incoming = Path(settings.incoming_dir)
    incoming.mkdir(parents=True, exist_ok=True)

    seen: Set[str] = set()

    api_url = os.getenv("EVENTPULSE_API_URL", "http://api:8080")

    print(f"[watcher] Watching {incoming} (poll={settings.watch_poll_seconds}s) → {api_url}/api/ingest/from_path")

    while True:
        for p in incoming.iterdir():
            if not p.is_file():
                continue
            name = p.name
            if name.startswith("."):
                continue
            # simple stability check: skip if size is changing
            size1 = p.stat().st_size
            time.sleep(0.2)
            size2 = p.stat().st_size
            if size1 != size2:
                continue

            # Avoid re-sending if API move failed and file remains
            if name in seen:
                continue

            # Heuristic dataset mapping: assume parcels_*.xlsx -> parcels
            dataset = "parcels"
            if "_" in name:
                dataset = name.split("_", 1)[0].lower()

            try:
                r = requests.post(
                    f"{api_url}/api/ingest/from_path",
                    json={"dataset": dataset, "relative_path": name, "source": "watcher"},
                    timeout=10,
                )
                if r.status_code == 200:
                    print(f"[watcher] Ingested {name}: {r.json().get('ingestion_id')}")
                    seen.add(name)
                else:
                    print(f"[watcher] Failed to ingest {name}: {r.status_code} {r.text[:200]}")
            except Exception as e:
                print(f"[watcher] Error ingesting {name}: {e}")

        time.sleep(settings.watch_poll_seconds)


if __name__ == "__main__":
    main()
