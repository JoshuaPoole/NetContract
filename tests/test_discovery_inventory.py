"""One source scan, distinct inventories, and evidence-gated Salesforce export."""
import io
import zipfile

from fastapi.testclient import TestClient

import app.main as main


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as bundle:
        bundle.writestr('models.py', 'from pydantic import BaseModel\nclass Incident(BaseModel):\n    ticket: str\n\ndef approve_incident():\n    return True\n')
        bundle.writestr('infra/main.tf', 'resource "aws_instance" "legacy" {}\n')
    return output.getvalue()


def test_discovery_and_salesforce_review_export_need_no_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path))
    client = TestClient(main.app)
    response = client.post('/api/analyze', files={'file': ('legacy.zip', archive(), 'application/zip')})
    assert response.status_code == 200
    inventory = response.json()['inventory']
    assert inventory['static_only']
    assert {item['name'] for item in inventory['business_contracts']} >= {'Incident', 'approve_incident'}
    assert inventory['terraform']['declarations'][0]['address'] == 'aws_instance.legacy'
    assert all(item['status'] == 'review' for item in inventory['business_contracts'])
    url = '/api/projects/' + response.json()['project_id'] + '/canonical'
    assert client.get(url + '/metadata.zip').status_code == 409
    plan = client.get(url + '/candidates').json()['review_plan']
    assert [item['concept'] for item in plan['entities']] == ['Incident']
    entity = plan['entities'][0]
    entity['status'] = 'approved'
    assert client.put(url + '/review', json=plan).status_code == 200
    assert client.get(url + '/metadata.zip').status_code == 400
    entity['fields'][0]['status'] = 'approved'
    assert client.put(url + '/review', json=plan).status_code == 200
    result = client.get(url + '/metadata.zip')
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as bundle:
        assert any('Incident' in name and name.endswith('field-meta.xml') for name in bundle.namelist())
        assert not any('aws_instance' in name for name in bundle.namelist())
    assert client.get('/reconstructed').status_code == 404


def test_bad_archive_is_rejected():
    response = TestClient(main.app).post('/api/analyze', files={'file': ('bad.zip', b'invalid', 'application/zip')})
    assert response.status_code == 400


def test_landing_page_is_discovery_only_and_salesforce_has_its_own_route():
    client = TestClient(main.app)
    landing = client.get('/')
    assert landing.status_code == 200
    assert 'id="irNodes"' in landing.text
    assert 'Evidence-backed repository preview' in landing.text
    assert 'id="businessRows"' in landing.text
    assert 'id="terraformRows"' in landing.text
    assert 'id="reviewEntities"' not in landing.text
    assert 'id="exportMetadata"' not in landing.text
    review = client.get('/salesforce')
    assert review.status_code == 200
    assert 'id="reviewEntities"' in review.text
    assert review.text.index('id="saveAndValidate"') < review.text.index('id="reviewEntities"')
    assert review.text.index('id="deploySalesforce"') < review.text.index('id="reviewEntities"')
    assert review.headers['Cache-Control'] == 'no-store'
    assert 'id="businessRows"' not in review.text
    for asset in ['common.js', 'discovery.js', 'salesforce-review.js', 'salesforce-deploy.js', 'discovery.css']:
        assert client.get('/assets/' + asset).status_code == 200
    assert client.get('/alex').status_code == 200


def test_discovery_snapshot_can_be_reopened_after_salesforce_navigation(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    client = TestClient(main.app)
    uploaded = client.post('/api/analyze', files={'file': ('legacy.zip', archive(), 'application/zip')}).json()
    restored = client.get('/api/projects/' + uploaded['project_id'] + '/discovery')
    assert restored.status_code == 200
    assert restored.json()['inventory'] == uploaded['inventory']
    assert restored.json()['ir'] == uploaded['ir']
    assert restored.json()['analysis']['repository_id'] == uploaded['analysis']['repository_id']
    assert client.get('/api/projects/missing/discovery').status_code == 404
