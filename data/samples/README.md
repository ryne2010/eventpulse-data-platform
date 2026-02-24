# Sample files

These files are **example inputs** for trying the platform.

They are intentionally stored outside `data/incoming/` so the watcher does not ingest them automatically.

Suggested workflow (local Docker Compose):

1. Start the stack:

   ```bash
   make up
   make watch
   ```

2. Copy a sample file into `data/incoming/`:

   ```bash
   cp data/samples/parcels_baseline.xlsx data/incoming/
   ```

3. Watch the UI as the watcher detects the new file and triggers ingestion.

Files:

- `parcels_baseline.xlsx` — valid baseline
  - includes synthetic Springfield, CO parcel rows with land-use categories used by dashboard analytics:
    `grassland`, `dry farmland`, and `irrigated farmland`
  - synthetic pricing targets roughly center around:
    - grassland: `$600/acre`
    - dry farmland: `$800/acre`
    - irrigated farmland: `$1500/acre`
    - structures: `$25-$300/sf`
- `parcels_drift_add_column.xlsx` — adds a new column (non-breaking drift)
- `parcels_drift_type_change.xlsx` — forces a type drift (e.g., `sale_price` becomes string)
- `parcels_quality_fail_duplicate_pk.xlsx` — fails quality gate (duplicate `parcel_id`)
