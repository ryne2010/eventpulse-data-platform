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
- `parcels_drift_add_column.xlsx` — adds a new column (non-breaking drift)
- `parcels_drift_type_change.xlsx` — forces a type drift (e.g., `sale_price` becomes string)
- `parcels_quality_fail_duplicate_pk.xlsx` — fails quality gate (duplicate `parcel_id`)

Edge telemetry (RPi demo):

- `edge_telemetry_sample.csv` — valid baseline
- `edge_telemetry_drift_add_column.csv` — adds a new column (non-breaking drift)
- `edge_telemetry_drift_type_change.csv` — forces a type drift (e.g., `rssi_dbm` becomes string)
- `edge_telemetry_quality_fail_duplicate_pk.csv` — fails quality gate (duplicate `event_id`)
