SHELL := /bin/bash

.PHONY: up down reset logs gen ingest list sample

up:
	cp -n .env.example .env || true
	docker compose up --build

down:
	docker compose down

reset:
	docker compose down -v
	rm -rf data/pg data/raw data/archive
	mkdir -p data/pg data/raw data/archive data/incoming data/contracts

logs:
	docker compose logs -f --tail=200

gen:
	python scripts/generate_sample_data.py --out ./data/incoming --rows 500

ingest:
	curl -s -X POST "http://localhost:8081/api/ingest/from_path" \
	  -H "Content-Type: application/json" \
	  -d '{"dataset":"parcels","relative_path":"parcels_baseline.xlsx","source":"make"}' | jq

list:
	curl -s "http://localhost:8081/api/ingestions?limit=20" | jq

sample:
	curl -s "http://localhost:8081/api/datasets/parcels/curated/sample?limit=10" | jq
