# Schema drift detection

EventPulse tracks and responds to **observed schema changes** for each dataset.

---

## How schemas are inferred

During ingestion processing, the worker:

1) loads the input file into a Pandas DataFrame
2) infers an **observed schema** from the DataFrame dtypes
3) computes a deterministic `schema_hash`
4) persists the schema to `dataset_schemas`

Observed types are simplified to:

- `string`
- `number`
- `boolean`
- `datetime`

---

## Drift types

Drift compares the **latest stored schema** for a dataset vs the **new observed schema**.

Detected changes include:

- `added_columns`: new fields appeared
- `removed_columns`: existing fields disappeared
- `changed_types`: existing fields changed inferred type

A drift is considered **breaking** if it removes columns or changes types.

---

## Drift policy

Each dataset contract can specify a drift policy:

- `warn` (default)
  - record drift details
  - continue processing
- `fail`
  - record drift details
  - mark ingestion `FAILED_DRIFT`
  - skip curated load
- `allow`
  - ignore drift (still recorded for observability)

---

## Where drift shows up

- **Quality report** (`quality_reports.report`)
  - `report.schema_drift` contains the drift summary
- **Lineage artifact** (`lineage_artifacts.artifact`)
  - includes schema hashes + drift summary

---

## Tips

- Use `parcels_drift_add_column.xlsx` to see a non-breaking drift event.
- Use `parcels_drift_type_change.xlsx` to see a breaking drift event.
