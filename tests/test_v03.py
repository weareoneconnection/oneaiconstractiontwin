import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
from fastapi.testclient import TestClient
from app.main import app

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def test_v03_ifc_schedule_mapping():
    with TestClient(app) as client:
        seeded=client.post('/api/v1/demo/seed').json(); pid=seeded['project_id']
        with open(os.path.join(ROOT,'data','demo_minimal.ifc'),'rb') as f:
            r=client.post(f'/api/v1/projects/{pid}/bim/import-ifc',files={'file':('demo.ifc',f,'application/octet-stream')})
        assert r.status_code==200, r.text
        assert r.json()['entities_created'] >= 3
        with open(os.path.join(ROOT,'data','demo_schedule.csv'),'rb') as f:
            r=client.post(f'/api/v1/projects/{pid}/schedules/import-csv',files={'file':('schedule.csv',f,'text/csv')})
        assert r.status_code==200, r.text
        assert r.json()['activities_created'] >= 3
        r=client.post(f'/api/v1/projects/{pid}/mappings/auto?threshold=0.12')
        assert r.status_code==200, r.text
        assert r.json()['mappings_created'] >= 1
        maps=client.get(f'/api/v1/projects/{pid}/mappings')
        assert maps.status_code==200
        assert len(maps.json()) >= 1
