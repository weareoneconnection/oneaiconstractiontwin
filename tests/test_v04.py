import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))
from fastapi.testclient import TestClient
from app.main import app

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def test_v04_geometry_and_4d_timeline():
    with TestClient(app) as client:
        seeded=client.post('/api/v1/demo/seed').json(); pid=seeded['project_id']
        with open(os.path.join(ROOT,'data','demo_minimal.ifc'),'rb') as f:
            r=client.post(f'/api/v1/projects/{pid}/bim/import-ifc',files={'file':('demo.ifc',f,'application/octet-stream')})
        assert r.status_code==200, r.text
        doc_id=r.json()['model_document_id']
        with open(os.path.join(ROOT,'data','demo_schedule.csv'),'rb') as f:
            r=client.post(f'/api/v1/projects/{pid}/schedules/import-csv',files={'file':('schedule.csv',f,'text/csv')})
        assert r.status_code==200, r.text
        r=client.post(f'/api/v1/projects/{pid}/mappings/auto?threshold=0.12')
        assert r.status_code==200, r.text
        g=client.get(f'/api/v1/projects/{pid}/bim/models/{doc_id}/geometry')
        assert g.status_code==200, g.text
        assert g.json()['mesh_count'] >= 3
        assert g.json()['geometry_mode'] in ('ifc-exact','hybrid','semantic-proxy')
        bounds=client.get(f'/api/v1/projects/{pid}/timeline')
        assert bounds.status_code==200
        assert bounds.json()['start'] <= bounds.json()['end']
        st=client.get(f'/api/v1/projects/{pid}/timeline/state?at=2026-08-18')
        assert st.status_code==200, st.text
        assert len(st.json()['entities']) >= 3
        assert sum(st.json()['summary'].values()) == len(st.json()['entities'])
