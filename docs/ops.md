# Ops Notes (Local)

## Common tasks
- Start: `docker compose up --build`
- Reset everything: `make reset`
- Generate sample data: `make gen`
- Ingest sample file: `make ingest`
- View ingestions: `make list`

## Troubleshooting
- API not starting: ensure ports 8081/5432/6379 are free
- Worker not processing: check redis/worker logs (`docker compose logs -f worker`)
- Missing contract: confirm `./data/contracts/<dataset>.yaml` exists
- Curated table not found: ingest must reach LOADED status first

## Security note
Local mode allows ingest-from-path under `INCOMING_DIR` only.
Do not expose this API to the public internet without authentication and additional controls.
