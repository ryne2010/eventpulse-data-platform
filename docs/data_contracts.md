# Data Contracts

Contracts live in YAML under `data/contracts/`.

Example: `parcels.yaml`

Contracts drive:
- required columns
- type expectations
- uniqueness (including primary key)
- numeric min/max constraints
- null fraction thresholds
- drift policy (warn/fail/allow)

This repo keeps contracts simple and readable so teams can treat them like
lightweight “data product” definitions.
