# Quick tour

This is a hands-on walkthrough for local development on macOS (M2 Max) using Docker Compose.

---

## 1) Start the stack

```bash
cp .env.example .env
make up
```

Open:

- UI: `http://localhost:8081`
- Health: `http://localhost:8081/health`

Optional (edge telemetry demo):

```bash
# Start simulated edge-agent that continuously uploads telemetry
make edge-up
```

Then open:

- Devices: `http://localhost:8081/devices`
- Dataset: `http://localhost:8081/datasets/edge_telemetry`

---

## 2) Ingest a valid file via the watcher

Start the watcher (once):

```bash
make watch
```

Then copy a sample into the incoming folder:

```bash
cp data/samples/parcels_baseline.xlsx data/incoming/
```

Within a few seconds:

- watcher detects the file
- API copies it to the raw landing zone
- API enqueues processing
- worker validates, detects drift, loads curated rows

In the UI, go to **Ingestions** and click a row to see:

- status
- quality report
- curated preview

---

## 3) Trigger a schema drift event

```bash
cp data/samples/parcels_drift_type_change.xlsx data/incoming/
```

The platform will:

- infer a new schema
- record drift details in the quality report
- still load the curated table (drift policy defaults to `warn`)

---

## 4) Trigger a quality failure

```bash
cp data/samples/parcels_quality_fail_duplicate_pk.xlsx data/incoming/
```

This ingestion should fail the quality gate because `parcel_id` (primary key) contains duplicates.

---

## 5) Replay an ingestion

From the UI, open any ingestion and click **Replay**.

Replay creates a **new ingestion record** referencing the same raw artifact, then processes it again.

---

## 6) Explore lineage

For any ingestion:

- API endpoint: `GET /api/ingestions/{id}/lineage`

The lineage artifact includes:

- raw path + sha256
- contract fingerprint
- observed schema hash
- drift summary
- quality summary
- load summary
- published endpoints

---

## 7) Explore Products, Trends, and the Audit log

Open the UI:

- **Products**: a catalog of published marts (consumption layer)
- **Trends**: quality pass/fail trend chart across recent ingestions
- **Audit**: operational audit trail for ingestion lifecycle, contract updates, and ops actions

Tip: open an ingestion detail and check the **Audit** tab to see worker lifecycle events.

