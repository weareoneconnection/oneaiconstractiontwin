import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
from fastapi.testclient import TestClient
from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


def test_demo_flow():
    with TestClient(app) as client:
        seeded = client.post("/api/v1/demo/seed")
        assert seeded.status_code == 200
        pid = seeded.json()["project_id"]
        projects = client.get("/api/v1/projects")
        assert projects.status_code == 200
        ask = client.post(f"/api/v1/projects/{pid}/ask", json={"question":"Why is the project delayed?"})
        assert ask.status_code == 200
        assert len(ask.json()["evidence"]) >= 1
        forecast = client.post(f"/api/v1/projects/{pid}/forecast")
        assert forecast.status_code == 200
        assert "p50" in forecast.json()["delay_days"]
        agent = client.post(f"/api/v1/projects/{pid}/agents/run", json={"agent":"schedule","task":"Review delay"})
        assert agent.status_code == 200
        aid = agent.json()["id"]
        approved = client.post(f"/api/v1/actions/{aid}/approve")
        assert approved.json()["status"] == "approved"
