"""Source-bound browser permissions and release adapter; no live Salesforce calls."""
import io
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import pytest

import app.main as main
import app.salesforce_browser as browser

HEADERS = {'Origin': 'http://127.0.0.1:8000', 'X-LifeAfterCode-Release': '1'}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path))
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setattr(browser.shutil, 'which', lambda _: 'sf')
    browser.JOBS.clear()
    browser.VALIDATIONS.clear()
    calls = []
    def execute(bundle, approve, assign):
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert 'canonical-review.json' in archive.namelist()
        calls.append((approve, assign))
        return 'Salesforce operation confirmed'
    monkeypatch.setattr(browser, 'execute_release', execute)
    client = TestClient(main.app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000))
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('models.py', 'from pydantic import BaseModel\nclass Incident(BaseModel):\n    ticket: str\n    summary: str\n')
    project = client.post('/api/analyze', files={'file': ('legacy.zip', payload.getvalue(), 'application/zip')}).json()['project_id']
    canonical = f'/api/projects/{project}/canonical'
    plan = client.get(canonical + '/candidates').json()['review_plan']
    plan['entities'][0]['status'] = 'approved'
    plan['entities'][0]['fields'][0]['status'] = 'approved'
    assert client.put(canonical + '/review', json=plan).status_code == 200
    base = f'/api/projects/{project}/salesforce'
    return client, base, plan, calls


def scope(client, base):
    reply = client.get(base + '/permissions')
    assert reply.status_code == 200, reply.text
    return reply.json()


def request_body(matrix, **extra):
    return {'org_alias': 'hackfest-developer', 'review_digest': matrix['review_digest'], **extra}


def test_permission_matrix_uses_existing_generator_and_only_approved_fields(prepared):
    client, base, _, _ = prepared
    matrix = scope(client, base)
    assert matrix['deployment_enabled']
    assert len(matrix['objects']) == 1
    assert len(matrix['fields']) == 1
    obj = matrix['objects'][0]
    assert obj['allowRead'] == obj['allowCreate'] == obj['allowEdit'] == 'true'
    assert obj['allowDelete'] == obj['modifyAllRecords'] == obj['viewAllRecords'] == 'false'
    assert matrix['fields'][0]['readable'] == matrix['fields'][0]['editable'] == 'true'
    assert matrix['application'].endswith('_App')


def test_browser_validation_then_deployment_reuses_saved_bundle_and_runner(prepared):
    client, base, _, calls = prepared
    matrix = scope(client, base)
    body = request_body(matrix)
    assert client.post(base + '/deploy', json=body, headers=HEADERS).status_code == 409
    validation = client.post(base + '/validate', json=body, headers=HEADERS)
    assert validation.status_code == 202
    job = client.get(base + '/jobs/' + validation.json()['job_id']).json()
    assert job['status'] == 'validated'
    result = client.post(base + '/deploy', json=request_body(matrix, assign_to_current_user=True), headers=HEADERS)
    assert result.status_code == 202
    assert client.get(base + '/jobs/' + result.json()['job_id']).json()['status'] == 'deployed'
    assert calls == [(False, False), (True, True)]
    # A deploy consumes its validation and cannot be replayed by another click.
    assert client.post(base + '/deploy', json=body, headers=HEADERS).status_code == 409


def test_review_edit_invalidates_earlier_validation(prepared):
    client, base, plan, calls = prepared
    matrix = scope(client, base)
    assert client.post(base + '/validate', json=request_body(matrix), headers=HEADERS).status_code == 202
    plan['entities'][0]['fields'][0]['target'] = 'ChangedTicket'
    assert client.put(base.replace('/salesforce', '/canonical/review'), json=plan).status_code == 200
    assert client.post(base + '/deploy', json=request_body(matrix), headers=HEADERS).status_code == 409
    updated = scope(client, base)
    assert updated['review_digest'] != matrix['review_digest']
    assert client.post(base + '/deploy', json=request_body(updated), headers=HEADERS).status_code == 409
    assert calls == [(False, False)]


@pytest.mark.parametrize('headers', [{}, {'Origin': 'https://attacker.invalid', 'X-LifeAfterCode-Release': '1'}, {'Origin': 'http://127.0.0.1:8000'}])
def test_release_requires_same_origin_and_explicit_browser_header(prepared, headers):
    client, base, _, calls = prepared
    response = client.post(base + '/validate', json=request_body(scope(client, base)), headers=headers)
    assert response.status_code == 403
    assert calls == []


def test_unapproved_org_and_validation_assignment_are_rejected(prepared):
    client, base, _, calls = prepared
    body = request_body(scope(client, base))
    assert client.post(base + '/validate', json={**body, 'org_alias': 'hackfest-dev'}, headers=HEADERS).status_code == 422
    assert client.post(base + '/validate', json={**body, 'assign_to_current_user': True}, headers=HEADERS).status_code == 400
    assert calls == []


def test_cli_or_local_enablement_missing_blocks_browser_release(prepared, monkeypatch):
    client, base, _, calls = prepared
    matrix = scope(client, base)
    monkeypatch.setattr(browser.shutil, 'which', lambda _: None)
    assert not scope(client, base)['deployment_enabled']
    assert client.post(base + '/validate', json=request_body(matrix), headers=HEADERS).status_code == 403
    monkeypatch.setattr(browser.shutil, 'which', lambda _: 'sf')
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '0')
    assert client.post(base + '/validate', json=request_body(matrix), headers=HEADERS).status_code == 403
    assert calls == []


def test_remote_client_cannot_trigger_local_cli(prepared):
    client, base, _, calls = prepared
    matrix = scope(client, base)
    remote = TestClient(main.app, base_url='http://127.0.0.1:8000', client=('192.0.2.15', 50000))
    assert remote.post(base + '/validate', json=request_body(matrix), headers=HEADERS).status_code == 403
    assert calls == []


def test_cli_failure_is_not_success_and_does_not_authorize_deployment(prepared, monkeypatch):
    client, base, _, _ = prepared
    def fail(*args):
        raise RuntimeError('Validation failed: field permission mismatch')
    monkeypatch.setattr(browser, 'execute_release', fail)
    matrix = scope(client, base)
    response = client.post(base + '/validate', json=request_body(matrix), headers=HEADERS)
    job = client.get(base + '/jobs/' + response.json()['job_id']).json()
    assert job['status'] == 'failed'
    assert 'permission mismatch' in job['log']
    assert client.post(base + '/deploy', json=request_body(matrix), headers=HEADERS).status_code == 409


def test_releases_are_serialized(prepared):
    client, base, _, calls = prepared
    browser.JOBS['active'] = {'status': 'running'}
    assert client.post(base + '/validate', json=request_body(scope(client, base)), headers=HEADERS).status_code == 409
    assert calls == []


def test_execute_release_calls_existing_entrypoint_with_bounded_flags(tmp_path, monkeypatch):
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        assert args[1] == str(browser.ROOT / 'run.py')
        assert args[2] == 'salesforce'
        assert args[args.index('--org') + 1] == 'hackfest-developer'
        assert '--approve' in args and '--assign-to-current-user' in args
        return SimpleNamespace(returncode=0, stdout='Deployment verified', stderr='')
    monkeypatch.setattr(browser.subprocess, 'run', command)
    assert browser.execute_release(b'bundle', True, True) == 'Deployment verified'
    assert len(calls) == 1


def test_frontend_configuration_is_reviewed_and_invalidates_prior_validation(prepared, monkeypatch):
    client, base, _, _ = prepared
    original = scope(client, base)
    assert original['frontend_url'] == ''
    assert client.post(base + '/validate', json=request_body(original), headers=HEADERS).status_code == 202
    url = 'https://mim.example/alexa'
    saved = client.put(base + '/frontend', json={'frontend_url': url}, headers=HEADERS)
    assert saved.status_code == 200
    assert client.get(base + '/frontend').json()['frontend_url'] == url
    updated = scope(client, base)
    assert updated['review_digest'] != original['review_digest']
    assert updated['workspace_tab'].endswith('_Workspace')
    assert client.post(base + '/deploy', json=request_body(updated), headers=HEADERS).status_code == 409
    seen = []
    def execute(bundle, approve, assign, frontend_url=''):
        seen.append(frontend_url)
        return 'Validated with workspace'
    monkeypatch.setattr(browser, 'execute_release', execute)
    result = client.post(base + '/validate', json=request_body(updated), headers=HEADERS)
    assert result.status_code == 202
    assert client.get(base + '/jobs/' + result.json()['job_id']).json()['status'] == 'validated'
    assert seen == [url]


def test_invalid_frontend_and_cross_origin_config_do_not_change_saved_target(prepared):
    client, base, _, _ = prepared
    assert client.put(base + '/frontend', json={'frontend_url': 'https://user:secret@mim.example/alexa'}, headers=HEADERS).status_code == 400
    assert client.put(base + '/frontend', json={'frontend_url': 'https://mim.example/alexa'}).status_code == 403
    assert client.get(base + '/frontend').json()['frontend_url'] == ''


def test_execute_release_passes_frontend_to_existing_cli_runner(monkeypatch):
    def command(args, **kwargs):
        assert args[args.index('--frontend-url') + 1] == 'https://mim.example/alexa'
        return SimpleNamespace(returncode=0, stdout='Workspace validated', stderr='')
    monkeypatch.setattr(browser.subprocess, 'run', command)
    assert browser.execute_release(b'bundle', False, False, 'https://mim.example/alexa') == 'Workspace validated'
