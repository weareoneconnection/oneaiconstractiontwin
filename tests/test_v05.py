import os, sys, json, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'apps', 'api'))
from fastapi.testclient import TestClient
from app.main import app

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def test_v05_glb_3dtiles_lod_and_spatial_streaming():
    with TestClient(app) as client:
        seeded=client.post('/api/v1/demo/seed').json(); pid=seeded['project_id']
        with open(os.path.join(ROOT,'data','demo_minimal.ifc'),'rb') as f:
            r=client.post(f'/api/v1/projects/{pid}/bim/import-ifc',files={'file':('demo.ifc',f,'application/octet-stream')})
        assert r.status_code==200, r.text
        doc_id=r.json()['model_document_id']
        r=client.post(f'/api/v1/projects/{pid}/bim/models/{doc_id}/assets/build?longitude=101.7&latitude=3.14&height=20')
        assert r.status_code==200, r.text
        body=r.json()
        assert body['format'].startswith('3D Tiles')
        assert body['entity_count'] >= 3
        assert all(len(x['lods']) == 3 for x in body['entities'])
        tileset=client.get(body['tileset_url'])
        assert tileset.status_code==200
        ts=tileset.json()
        assert ts['asset']['version']=='1.1'
        assert len(ts['root']['children']) >= 3
        first=body['entities'][0]
        glb_url=body['tileset_url'].rsplit('/',1)[0]+'/'+first['lods'][0]['uri']
        glb=client.get(glb_url)
        assert glb.status_code==200
        assert glb.content[:4] == b'glTF'
        q=client.get(f'/api/v1/projects/{pid}/bim/models/{doc_id}/spatial-stream?minx=-100&miny=-100&minz=-100&maxx=100&maxy=100&maxz=100')
        assert q.status_code==200
        assert q.json()['count'] >= 3
