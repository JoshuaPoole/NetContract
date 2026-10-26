"""Hosted judge access uses actual credentials, never a trusted username header."""
import base64
import io
import json
import stat
import zipfile

from fastapi.testclient import TestClient
import pytest

from app import main
from app import salesforce_browser as browser
from app import alex_workspace as alex
from scripts.configure_judge_access import configure

ORIGIN = 'https://3-25-74-9.sslip.io'
PASSWORD = 'test-only-password'
AUTH = 'Basic ' + base64.b64encode(f'judges:{PASSWORD}'.encode()).decode()
HEADERS = {'Authorization': AUTH, 'Origin': ORIGIN, 'X-LifeAfterCode-Release': '1'}


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    config = configure(ORIGIN, 'judges', PASSWORD, tmp_path/'private/access.json')
    monkeypatch.setenv('NETCONTRACT_JUDGE_CONFIG', str(config))
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path/'workspace'))
    monkeypatch.setattr(main, 'DATA', tmp_path/'workspace')
    main.DATA.mkdir()
    monkeypatch.setattr(browser.shutil, 'which', lambda _: 'sf')
    browser.JOBS.clear()
    browser.VALIDATIONS.clear()
    calls = []
    monkeypatch.setattr(browser, 'execute_release', lambda bundle, approve, assign: calls.append(approve) or 'Confirmed')
    client = TestClient(main.app, base_url=ORIGIN, client=('192.0.2.20', 50000))
    return client, calls, config


def test_protects_pages_assets_uploads_and_api_without_credentials(hosted):
    client, calls, _ = hosted
    for path in ('/', '/alexa', '/assets/alex.js', '/api/projects/demo/salesforce/records'):
        response = client.get(path)
        assert response.status_code == 401 and 'Basic' in response.headers['www-authenticate']
    for auth in ('Basic bad!', 'Bearer guessed', 'Basic ' + base64.b64encode(b'judges:wrong').decode()):
        assert client.get('/', headers={'Authorization': auth}).status_code == 401
    assert client.post('/api/analyze').status_code == 401
    assert not calls


def test_host_protocol_origin_and_browser_header_remain_required(hosted):
    client, calls, _ = hosted
    assert client.get('/', headers=HEADERS).status_code == 200
    for base in ('http://3-25-74-9.sslip.io','https://attacker.invalid'):
        other = TestClient(main.app, base_url=base, client=('192.0.2.20', 50000))
        assert other.get('/', headers=HEADERS).status_code == 403
    for origin in (None, 'null', 'https://attacker.invalid'):
        headers = dict(HEADERS)
        if origin is None: headers.pop('Origin')
        else: headers['Origin'] = origin
        assert client.post('/api/projects/demo/alexa/config', headers=headers).status_code == 403
    assert client.post('/api/projects/demo/alexa/config', headers={'Authorization': AUTH, 'Origin': ORIGIN}).status_code == 403
    assert client.get('/', headers={'X-Forwarded-User':'judges','X-Forwarded-For':'127.0.0.1','X-Forwarded-Proto':'https'}).status_code == 401
    assert not calls


def test_public_upload_review_preview_validate_deploy_and_job_poll(hosted,monkeypatch):
    client, calls, _ = hosted
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('data/procedures.json', json.dumps([{'dip_id':'NEW-REPO-COOLING-42', 'title':'Router cooling failure', 'implementation_steps':['Inspect temperature readings','Review cooling status']}]))
    response = client.post('/api/analyze', headers=HEADERS, files={'file':('legacy.zip', archive.getvalue(), 'application/zip')})
    assert response.status_code == 200, response.text
    project = response.json()['project_id']
    canonical = f'/api/projects/{project}/canonical'
    plan = client.get(canonical+'/candidates', headers=HEADERS).json()['review_plan']
    plan['entities'][0]['status'] = 'approved'
    for field in plan['entities'][0]['fields']:
        if field['source'].endswith(('.dip_id','.title','.implementation_steps')):
            field['status'] = 'approved'
    assert client.put(canonical+'/review', headers=HEADERS, json=plan).status_code == 200
    base = f'/api/projects/{project}/salesforce'
    preview = client.get(base+'/records', headers=HEADERS)
    assert preview.status_code == 200, preview.text
    assert preview.json()['record_count'] == 1
    matrix = client.get(base+'/permissions', headers=HEADERS).json()
    assert matrix['deployment_enabled']
    body = {'review_digest':matrix['review_digest'], 'org_alias':'hackfest-developer'}
    assert client.post(base+'/deploy', headers=HEADERS, json=body).status_code == 409
    assert client.post(base+'/validate', headers=HEADERS, json=body).status_code == 202
    sf_records = []
    def sync(records, approval, executable):
        assert approval == records['review_digest']
        for batch in records['batches']:
            sf_records.extend({'Id':'new-sf-record', **row} for row in batch['rows'])
        return [{'state':'JobComplete','failed':0,'processed':1}]
    monkeypatch.setattr('scripts.seeded_network_sf.apply',sync)
    response = client.post(base+'/deploy', headers=HEADERS, json={**body, 'sync_records':True, 'record_digest':preview.json()['record_digest']})
    assert response.status_code == 202, response.text
    job = client.get(base+'/jobs/'+response.json()['job_id'], headers=HEADERS).json()
    assert job['status'] == 'deployed' and calls == [False, True]
    monkeypatch.setattr(alex,'query_salesforce',lambda _:sf_records)
    assert client.post('/api/alexa/config',headers=HEADERS).json()['project_id'] == project
    result = client.post('/api/alexa/ask',headers=HEADERS,json={'question':'router cooling failure'}).json()
    assert result['records'][0]['procedure_id'] == 'NEW-REPO-COOLING-42'
    assert 'Inspect temperature readings' in result['records'][0]['values']['implementation_steps']
    assert client.post(base+'/deploy', headers=HEADERS, json=body).status_code == 409


def test_alexa_salesforce_reader_accepts_hosted_judge_login(hosted, monkeypatch):
    client, _, _ = hosted
    monkeypatch.setattr(alex, 'published', lambda *a:{'object':'Rtest_DIP__c','identity':'Dip_Id__c','fields':{'Dip_Id__c':'dip_id','Title__c':'title'}, 'allowed_ids':['LAB-BFD'],'publication_digest':'frozen','incident':None})
    monkeypatch.setattr(alex, 'query_salesforce', lambda _:[{'Id':'SF-1','Dip_Id__c':'LAB-BFD','Title__c':'BFD failure'}])
    response = client.post('/api/projects/demo/alex/ask', headers=HEADERS, json={'question':'BFD failure'})
    assert response.status_code == 200, response.text
    assert response.json()['records'][0]['record_id'] == 'SF-1'
    assert not response.json()['execution_enabled']


def test_invalid_config_fails_closed_but_local_tunnel_still_works(hosted):
    client, _, config = hosted
    config.write_text('{}')
    assert client.get('/', headers=HEADERS).status_code == 503
    local = TestClient(main.app, base_url='http://localhost:8000', client=('127.0.0.1', 50000))
    assert local.get('/').status_code == 200
    remote = TestClient(main.app, base_url='http://localhost:8000', client=('192.0.2.1', 50000))
    assert remote.get('/').status_code == 503


def test_configuration_persists_hash_only_with_private_permissions(hosted):
    _, _, path = hosted
    config = json.loads(path.read_text())
    assert PASSWORD not in path.read_text()
    assert config['origin'] == ORIGIN
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob('.judge-*'))


@pytest.mark.parametrize('origin',['http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com?query=1'])
def test_invalid_origin_never_writes_configuration(tmp_path,origin):
    with pytest.raises(ValueError): configure(origin,'judges',PASSWORD,tmp_path/'access.json')
    assert not (tmp_path/'access.json').exists()


def test_proxy_headers_are_accepted_only_from_loopback(hosted):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    wrapped = ProxyHeadersMiddleware(main.app, trusted_hosts='127.0.0.1,::1')
    headers = {**HEADERS,'X-Forwarded-Proto':'https','X-Forwarded-For':'192.0.2.20'}
    proxy = TestClient(wrapped,base_url='http://3-25-74-9.sslip.io',client=('127.0.0.1',55000))
    assert proxy.get('/',headers=headers).status_code == 200
    untrusted = TestClient(wrapped,base_url='http://3-25-74-9.sslip.io',client=('192.0.2.20',55000))
    assert untrusted.get('/',headers=headers).status_code == 403
    assert proxy.get('/',headers={'X-Forwarded-Proto':'https','X-Forwarded-For':'127.0.0.1','X-Forwarded-User':'judges'}).status_code == 401
