SHELL := /bin/bash
PY := apps/api/.venv/bin/python

.PHONY: install api worker web test verify migrate e2e backup restore compose compose-workers monitoring build-web

install:
	./scripts/bootstrap-local.sh

api:
	./scripts/run-api.sh

worker:
	./scripts/run-worker.sh

web:
	./scripts/run-web.sh

build-web:
	cd apps/web && if [ -f package-lock.json ]; then npm ci --registry=https://registry.npmjs.org; else npm install --registry=https://registry.npmjs.org; fi && npm run build

test:
	@test -x $(PY) || (echo "Run make install first" >&2; exit 1)
	PYTHONPATH=apps/api $(PY) -m pytest -q

verify:
	./scripts/verify.sh

migrate:
	@test -x $(PY) || (echo "Run make install first" >&2; exit 1)
	cd apps/api && .venv/bin/python scripts/migrate.py

e2e:
	@test -x $(PY) || (echo "Run make install first" >&2; exit 1)
	$(PY) scripts/e2e_pilot.py

backup:
	./scripts/backup.sh

restore:
	@echo "Use: ./scripts/restore.sh <backup-directory> RESTORE"

compose:
	docker compose up --build

compose-workers:
	docker compose up --build --scale asset-worker=3

monitoring:
	docker compose --profile monitoring up --build
