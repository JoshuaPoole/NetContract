import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import mim_incidents as mim


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    config = {'incident': {'object': 'R7ac51ef9_Incident__c', 'service': 'Service__c',
                          'short_description': 'Summary__c'},
              'catalog': {'source_evidence': ['reviewed repo:dip.py:12'], 'dips': [
                  {'dip_id': 'bfd', 'title': 'BFD session down', 'category': 'BFD failure',
                   'service': 'network', 'review_status': 'approved',
                   'implementation_steps': ['Collect BFD peer diagnostics'],
                   'validation_steps': ['Inspect BFD session timers'], 'approval_groups': ['Network engineers']}]}}
    path = tmp_path / 'mim.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('LIFEAFTERCODE_MIM_CONFIG', str(path))
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setattr('shutil.which', lambda _: '/usr/bin/sf')
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    return client, config, path


HEADERS = {'Origin': 'http://localhost', 'X-LifeAfterCode-Release': '1'}
ROW = {'Id': 'a00123456789012AAA', 'LastModifiedDate': '2026-10-25T00:00:00Z',
       'Service__c': 'network', 'Summary__c': 'BFD session down peer timers', 'Secret__c': 'must not return'}


def test_live_read_and_advisory_reuses_matcher(runtime, monkeypatch):
    client, _, _ = runtime
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 0, 'result': {'records': [ROW]}}))
    monkeypatch.setattr(mim.subprocess, 'run', run)
    listing = client.post('/api/mim/incidents', headers=HEADERS)
    assert listing.status_code == 200
    assert listing.json()['records'][0]['title'] == ROW['Summary__c']
    result = client.post('/api/mim/recommend', json={'record_id': ROW['Id']}, headers=HEADERS)
    assert result.status_code == 200
    data = result.json()
    assert data['recommendation']['recommended_dip_id'] == 'bfd'
    assert data['evidence']['record_id'] == ROW['Id']
    assert len(data['evidence']['record_digest']) == 64
    assert data['approval_status'] == 'requires_human_review'
    assert not data['write_back_enabled'] and not data['execution_enabled']
    assert 'Secret__c' not in result.text
    assert all(args[1:3] == ['data', 'query'] for args in calls)
    assert all('hackfest-developer' in args for args in calls)
    assert "WHERE Id = 'a00123456789012AAA'" in calls[1][calls[1].index('--query') + 1]


def test_no_cross_origin_or_remote_reads(runtime):
    client, _, _ = runtime
    assert client.post('/api/mim/incidents').status_code == 403
    assert client.post('/api/mim/incidents', headers={**HEADERS, 'Origin': 'https://attacker.example'}).status_code == 403
    remote = TestClient(app, base_url='https://company.example', client=('10.0.0.1', 50000))
    assert remote.post('/api/mim/incidents', headers={'Origin': 'https://company.example', 'X-LifeAfterCode-Release': '1'}).status_code == 403


def test_config_never_guesses_fields_or_catalog(runtime):
    client, config, path = runtime
    config['incident']['service'] = 'Service__c FROM Account'
    path.write_text(json.dumps(config))
    assert client.post('/api/mim/incidents', headers=HEADERS).status_code == 409
    config['incident']['service'] = 'Service__c'
    config['catalog']['dips'][0]['review_status'] = 'needs_review'
    path.write_text(json.dumps(config))
    assert client.post('/api/mim/incidents', headers=HEADERS).status_code == 409


def test_query_failure_does_not_disclose_cli_diagnostics(runtime, monkeypatch):
    client, _, _ = runtime
    monkeypatch.setattr(mim.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='private-token'))
    response = client.post('/api/mim/incidents', headers=HEADERS)
    assert response.status_code == 502
    assert 'private-token' not in response.text


def test_no_records_and_invalid_selection(runtime, monkeypatch):
    client, _, _ = runtime
    monkeypatch.setattr(mim, 'query_records', lambda *a: [])
    assert client.post('/api/mim/incidents', headers=HEADERS).json()['records'] == []
    assert client.post('/api/mim/recommend', json={'record_id': ROW['Id']}, headers=HEADERS).status_code == 404
    assert client.post('/api/mim/recommend', json={'record_id': "' OR Name != ''"}, headers=HEADERS).status_code == 422


def test_missing_configuration_is_explicit(runtime, monkeypatch):
    client, _, _ = runtime
    monkeypatch.delenv('LIFEAFTERCODE_MIM_CONFIG')
    assert client.post('/api/mim/incidents', headers=HEADERS).status_code == 409


def test_ambiguous_catalog_abstains(runtime, monkeypatch):
    client, config, path = runtime
    other = dict(config['catalog']['dips'][0], dip_id='bfd-other')
    config['catalog']['dips'].append(other)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(mim, 'query_records', lambda *a: [ROW])
    data = client.post('/api/mim/recommend', json={'record_id': ROW['Id']}, headers=HEADERS).json()
    assert data['recommendation']['recommended_dip_id'] is None
    assert data['plan'] is None


def test_hosted_snapshot_boundary_and_field_allowlist(runtime, monkeypatch):
    client, _, _ = runtime
    monkeypatch.setenv('LIFEAFTERCODE_SF_PARENT_ORIGINS', 'https://demo.lightning.force.com')
    assert client.get('/api/mim/bridge').json()['parent_origins'] == ['https://demo.lightning.force.com']
    # Hosted evaluation needs no CLI and never queries Salesforce.
    monkeypatch.setattr(mim, 'query_records', lambda *a: pytest.fail('Hosted snapshots must not query CLI'))
    response = client.post('/api/mim/advise-snapshot', headers=HEADERS,
                           json={'object': 'R7ac51ef9_Incident__c', 'record': ROW})
    assert response.status_code == 200
    data = response.json()
    assert data['recommendation']['recommended_dip_id'] == 'bfd'
    assert data['evidence']['source'] == 'salesforce_browser_snapshot'
    assert data['evidence']['org_alias'] is None
    assert not data['evidence']['authorization_evidence_trusted']
    assert 'Secret__c' not in response.text
    assert client.post('/api/mim/advise-snapshot', json={'object': 'R7ac51ef9_Incident__c', 'record': ROW}).status_code == 403
    assert client.post('/api/mim/advise-snapshot', headers=HEADERS, json={'object': 'Other__c', 'record': ROW}).status_code == 409
    assert client.post('/api/mim/advise-snapshot', headers=HEADERS, json={'object': 'R7ac51ef9_Incident__c', 'record': {'Id': ROW['Id']}}).status_code == 409


def test_hosted_origins_reject_wildcard(runtime, monkeypatch):
    client, _, _ = runtime
    monkeypatch.setenv('LIFEAFTERCODE_SF_PARENT_ORIGINS', 'https://*.force.com')
    assert client.get('/api/mim/bridge').status_code == 409


def test_scoped_apex_generated_only_for_mim_frontend(tmp_path):
    from scripts.salesforce_deploy_playbook import generate_permissions, generate_lightning_app
    objects = {'R7ac51ef9_Incident__c': ['Service__c', 'Summary__c']}
    name = generate_permissions(objects, tmp_path / 'permissionsets')
    generate_lightning_app(objects, tmp_path, name, 'LifeAfterCode', 'https://company.example/mim')
    code = next((tmp_path / 'classes').glob('*Reader*.cls')).read_text()
    # Select the production class, not the generated test class.
    code = next(path for path in (tmp_path / 'classes').glob('*.cls') if not path.stem.endswith('Test')).read_text()
    assert 'with sharing' in code and 'AccessLevel.USER_MODE' in code
    assert "'R7ac51ef9_Incident__c' => 'Service__c, Summary__c'" in code
    assert 'allowed.containsKey(objectName)' in code
    assert 'WHERE Id = :selectedId' in code
    assert 'insert ' not in code and 'update ' not in code and 'delete ' not in code
    permission = next((tmp_path / 'permissionsets').glob('*.xml')).read_text()
    assert '<classAccesses>' in permission
    javascript = next((tmp_path / 'lwc').glob('*/*.js')).read_text()
    assert '__RECORD_' not in javascript and '__BRIDGE_' not in javascript
    assert 'postMessage' in javascript and 'new URL(this.frontendUrl).origin' in javascript
    assert "bridgeEnabled = true" in javascript


def test_frontend_rejects_messages_from_other_windows_and_origins():
    import subprocess
    from pathlib import Path
    harness = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const events = {}, calls = [], parent = {postMessage: () => {}};
const elements = new Map();
const document = {querySelector: key => {
    if (!elements.has(key)) elements.set(key, {value: '', addEventListener(){}, replaceChildren(){}, append(){}});
    return elements.get(key);
}};
const context = {document, window: {parent, addEventListener: (key, callback) => {events[key] = callback;}},
    fetch: async (path, options) => {
        calls.push(path);
        return {ok: true, json: async () => path.endsWith('/bridge') ? {parent_origins: ['https://demo.lightning.force.com']} : {recommendation: {}}};
    }};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
(async () => {
    await new Promise(resolve => setImmediate(resolve));
    const message = {type: 'lifeaftercode.incident.v1', object: 'Incident__c', record: {Id: 'a00123456789012AAA'}};
    await events.message({origin: 'https://attacker.example', source: parent, data: message});
    await events.message({origin: 'https://demo.lightning.force.com', source: {}, data: message});
    assert.equal(calls.length, 1);
    await events.message({origin: 'https://demo.lightning.force.com', source: parent, data: message});
    assert.equal(calls[1], '/api/mim/advise-snapshot');
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run(['node', '-e', harness, str(Path(__file__).resolve().parents[1] / 'app/assets/mim-incidents.js')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
