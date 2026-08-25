# Run OneAI Construction Twin v0.7.0 Enterprise Pilot Edition

## A. Local development

### Terminal 1 - API
```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-ifc.txt  # optional, recommended
python scripts/migrate.py
python -m uvicorn app.main:app --reload
```

### Terminal 2 - Asset worker
```bash
cd apps/api
source .venv/bin/activate
python -m app.workers.asset_worker
```

### Terminal 3 - Web
```bash
cd apps/web
cp .env.local.example .env.local
npm install --registry=https://registry.npmjs.org
npm run dev
```

### Terminal 4 - E2E pilot chain
```bash
python scripts/e2e_pilot.py
```

Open:
- Web: `http://localhost:3000`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/health/ready`
- Metrics: `http://127.0.0.1:8000/metrics`

## B. Docker development stack

```bash
cp .env.example .env
docker compose up --build --scale asset-worker=2
```

Optional monitoring:

```bash
docker compose --profile monitoring up --build --scale asset-worker=2
```

## C. Production-oriented compose override

1. Copy `.env.enterprise.example` to a secure environment file.
2. Replace every placeholder secret.
3. Configure a real OIDC provider and HTTPS termination.
4. Run migration as a controlled release step.
5. Start the production stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml --profile migration run --rm migration

docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build --scale asset-worker=3
```

Production configuration intentionally disables demo endpoints and development header authentication.

## D. Release gate

```bash
make test
make verify
```

Then complete the manual acceptance checklist in `docs/PILOT_RUNBOOK.md`.
