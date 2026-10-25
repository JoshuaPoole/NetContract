import io
import json
import zipfile

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app import salesforce_browser as browser
from app.procedure_sync import record_plan


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path))
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setattr('app.main.DATA', tmp_path)
    monkeypatch.setattr('shutil.which', lambda *a: 'sf')
    browser.JOBS.clear()
    browser.VALIDATIONS.clear()
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    output = io.BytesIO()
    records = [{'dip_id': 'LAB-1', 'title': 'Secret unapproved title', 'service': 'network',
                'implementation_steps': ['Inspect BFD'], 'description': 'sensitive unapproved value'},
               {'dip_id': 'LAB-2', 'title': 'Second', 'implementation_steps': ['Inspect peer']}]
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('data/procedures.json', json.dumps(records))
    project = client.post('/api/analyze', files={'file': ('source.zip', output.getvalue())}).json()['project_id']
    review = client.get(f'/api/projects/{project}/canonical/candidates').json()['review_plan']
    entity = review['entities'][0]
    entity['status'] = 'approved'
    for field in entity['fields']:
        if field['source'].endswith(('.dip_id', '.implementation_steps', '.service')):
            field['status'] = 'approved'
    headers = {'Origin': 'http://localhost', 'X-LifeAfterCode-Release': '1'}
    assert client.put(f'/api/projects/{project}/canonical/review', json=review).status_code == 200
    return client, project, review, headers


def test_sync_uses_only_approved_fields_and_keeps_missing_properties(setup):
    client, project, _, _ = setup
    plan = record_plan(project)
    assert len(plan['batches']) == 2
    rows = [row for batch in plan['batches'] for row in batch['rows']]
    assert {row['Dip_Id__c'] for row in rows} == {'LAB-1', 'LAB-2'}
    assert all(row['Name'] == row['Dip_Id__c'] for row in rows)
    assert 'Secret unapproved title' not in json.dumps(plan)
    assert 'sensitive unapproved value' not in json.dumps(plan)
    assert 'Service__c' not in next(row for row in rows if row['Dip_Id__c'] == 'LAB-2')
    preview = client.get(f'/api/projects/{project}/salesforce/records')
    assert preview.status_code == 200
    assert preview.json()['record_count'] == 2
    assert record_plan(project) == plan
    metadata = client.get(f'/api/projects/{project}/canonical/metadata.zip')
    with zipfile.ZipFile(io.BytesIO(metadata.content)) as archive:
        key = next(name for name in archive.namelist() if name.endswith('/Dip_Id__c.field-meta.xml'))
        assert '<externalId>true</externalId><unique>true</unique>' in archive.read(key).decode()


def test_unique_identity_requires_review_and_schema_redeployment(setup):
    client, project, review, _ = setup
    field = next(f for f in review['entities'][0]['fields'] if f['external_id'])
    field['external_id'] = False
    assert client.put(f'/api/projects/{project}/canonical/review', json=review).status_code == 200
    assert client.get(f'/api/projects/{project}/salesforce/records').status_code == 400
    field['external_id'] = True
    field['status'] = 'rejected'
    assert client.put(f'/api/projects/{project}/canonical/review', json=review).status_code == 200
    with pytest.raises(ValueError, match='exactly one'):
        record_plan(project)


def test_deploy_then_sync_uses_saved_digests_and_existing_importer(setup, monkeypatch):
    client, project, _, headers = setup
    calls = []
    monkeypatch.setattr(browser, 'execute_release', lambda bundle, approve, assign: calls.append(('deploy', approve)) or 'Schema operation succeeded')
    def apply(plan, approval, executable):
        calls.append(('sync', plan['review_digest']))
        assert approval == plan['review_digest']
        return [{'state': 'JobComplete', 'failed': 0}]
    monkeypatch.setattr('scripts.seeded_network_sf.apply', apply)
    base = f'/api/projects/{project}/salesforce'
    matrix = client.get(base+'/permissions').json()
    digest = client.get(base+'/records').json()['record_digest']
    payload = {'review_digest': matrix['review_digest']}
    assert client.post(base+'/validate', json={**payload, 'sync_records': True}, headers=headers).status_code == 400
    assert client.post(base+'/deploy', json={**payload, 'sync_records': True, 'record_digest': digest}, headers=headers).status_code == 409
    assert client.post(base+'/validate', json=payload, headers=headers).status_code == 202
    deployed = client.post(base+'/deploy', json={**payload, 'sync_records': True, 'record_digest': digest}, headers=headers)
    assert deployed.status_code == 202, deployed.text
    job = client.get(base+'/jobs/'+deployed.json()['job_id']).json()
    assert job['status'] == 'deployed' and job['schema_deployed']
    assert calls[0] == ('deploy', False)
    assert calls[1] == ('deploy', True)
    assert calls[2][0] == 'sync'
    assert 'record sync confirmed' in job['log']


def test_stale_record_preview_or_failed_upsert_never_claims_complete_success(setup, monkeypatch):
    client, project, _, headers = setup
    monkeypatch.setattr(browser, 'execute_release', lambda *a: 'Schema deployed successfully')
    base = f'/api/projects/{project}/salesforce'
    payload = {'review_digest': client.get(base+'/permissions').json()['review_digest']}
    assert client.post(base+'/validate', json=payload, headers=headers).status_code == 202
    stale = client.post(base+'/deploy', json={**payload, 'sync_records': True, 'record_digest': '0'*64}, headers=headers)
    assert stale.status_code == 409
    def fail(*args):
        raise RuntimeError('Bulk job JOB123 has failed records')
    monkeypatch.setattr('scripts.seeded_network_sf.apply', fail)
    record_digest = client.get(base+'/records').json()['record_digest']
    result = client.post(base+'/deploy', json={**payload, 'sync_records': True, 'record_digest': record_digest}, headers=headers)
    job = client.get(base+'/jobs/'+result.json()['job_id']).json()
    assert job['status'] == 'failed' and job['schema_deployed']
    assert 'Schema deployed successfully' in job['log'] and 'JOB123' in job['log']
