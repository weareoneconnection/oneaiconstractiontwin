# Run Alpha v0.2

## Terminal 1 — API
```bash
cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

API: http://127.0.0.1:8000
Docs: http://127.0.0.1:8000/docs

Seed if needed:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/demo/seed
```

## Terminal 2 — Web
```bash
cd apps/web
npm install --registry=https://registry.npmjs.org
npm run dev
```

Open: http://localhost:3000

The UI automatically seeds a demo project if the API database is empty.
