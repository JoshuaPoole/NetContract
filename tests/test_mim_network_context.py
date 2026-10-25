from datetime import datetime, timezone, timedelta
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app import mim_incidents as mim
from app.mim_network_context import NetworkContext, evaluate_context, read_context
from app.seeded_network_import import digest

NOW = datetime(2026, 10, 25, 8, tzinfo=timezone.utc)
NODE = digest({'namespace': 'demo', 'kind': 'node', 'identity': 'NODE-00001'})
SETTINGS = NetworkContext(lab_namespace='demo')


def observation(status='attention', signal=True, when=NOW, node='NODE-00001'):
    payload = {'device_id': node, 'observed_at': when.isoformat(), 'simulation_only': True,
               'status': status, 'sample': {'alarm_observations': {'bfd.session_down': signal}}}
    return {'Id': 'a00123456789012AAA', 'EvidenceKind__c': 'observation', 'LabNamespace__c': 'demo',
            'NodeKey__c': NODE, 'SourceKey__c': digest({'namespace': 'demo', 'kind': 'observation',
                'identity': [node, payload['observed_at'], digest(payload)]}),
            'SourceDigest__c': digest(payload), 'EvidenceJSON__c': json.dumps(payload),
            'ProvenanceKind__c': 'synthetic'}


def contract(identifier='BFD', signal='bfd.session_down', service='SYNTHETIC-NETWORK'):
    payload = {'dip_id': identifier, 'title': 'BFD session down', 'service': service,
               'provenance': {'kind': 'synthetic'}, 'execution_enabled': False,
               'trigger': {'signal': signal, 'equals': True, 'requires_fresh': True}}
    return {'Id': 'a00123456789013AAA', 'ContractJSON__c': json.dumps(payload),
            'ContractDigest__c': digest(payload), 'CatalogKey__c': digest({'dip_id': identifier, 'version': '1'}),
            'CatalogReviewStatus__c': 'approved', 'ProvenanceKind__c': 'synthetic'}


def evaluate(evidence=None, catalog=None):
    return evaluate_context(SETTINGS, NODE, 'SYNTHETIC-NETWORK',
                            evidence if evidence is not None else [observation()],
                            catalog if catalog is not None else [contract()], now=NOW)


def test_fresh_signal_drives_plan_with_salesforce_evidence():
    result = evaluate()
    assert result['recommendation']['recommended_dip_id'] == 'BFD'
    assert result['recommendation']['method'] == 'synthetic_observation_contract_v1'
    assert result['network_evidence']['observation_record_id'] == 'a00123456789012AAA'
    assert result['network_evidence']['catalog_records'][0]['record_id'] == 'a00123456789013AAA'
    assert len(result['recommendation']['evidence_digest']) == 64
    assert not result['write_back_enabled'] and not result['execution_enabled']


@pytest.mark.parametrize('row', [observation(when=NOW-timedelta(hours=1)),
    observation(when=NOW+timedelta(minutes=1)), observation(node='OTHER')])
def test_stale_future_and_unrelated_evidence_block_decision(row):
    with pytest.raises(HTTPException) as error:
        evaluate([row])
    assert error.value.status_code == 409


@pytest.mark.parametrize('value', [False, None, 'true', 1])
def test_only_explicit_boolean_signal_matches(value):
    assert evaluate([observation(signal=value)])['plan'] is None


def test_latest_healthy_or_unknown_does_not_resurrect_old_alarm():
    older = observation(when=NOW-timedelta(minutes=1))
    assert evaluate([older, observation(status='healthy')])['plan'] is None
    assert evaluate([older, observation(status='unknown')])['plan'] is None


def test_conflicting_latest_catalog_or_content_abstains():
    with pytest.raises(HTTPException):
        evaluate([observation(), observation(status='healthy')])
    bad = observation()
    bad['SourceDigest__c'] = 'tampered'
    with pytest.raises(HTTPException):
        evaluate([bad])
    with pytest.raises(HTTPException):
        evaluate(catalog=[contract(), contract()])
    ambiguous = evaluate(catalog=[contract(), contract('BFD-2')])
    assert ambiguous['recommendation']['status'] == 'ambiguous' and ambiguous['plan'] is None


def test_unapproved_catalog_is_never_used_or_replaced_with_local_data():
    unapproved = contract()
    unapproved['CatalogReviewStatus__c'] = 'needs_review'
    with pytest.raises(HTTPException):
        evaluate(catalog=[unapproved])
    assert evaluate(catalog=[])['plan'] is None
    assert evaluate(catalog=[contract(service='OTHER')])['plan'] is None
    with pytest.raises(HTTPException):
        evaluate(evidence=[])


def test_queries_use_exact_node_lab_scope_and_bound_results():
    calls = []
    def reader(query):
        calls.append(query)
        return []
    read_context(SETTINGS, NODE, reader)
    assert f"NodeKey__c = '{NODE}'" in calls[0] and "LabNamespace__c = 'demo'" in calls[0]
    assert "EvidenceKind__c = 'observation'" in calls[0]
    assert "CatalogReviewStatus__c = 'approved'" in calls[1]
    with pytest.raises(HTTPException):
        read_context(SETTINGS, "' OR Name != ''", reader)
    with pytest.raises(HTTPException):
        read_context(SETTINGS, NODE, lambda q: [{}]*201)


def test_configured_incident_route_reads_real_context(tmp_path, monkeypatch):
    config = {'incident': {'object': 'R7ac51ef9_Incident__c', 'service': 'Service__c',
                          'short_description': 'Summary__c', 'node_key': 'NodeKey__c'},
              'network_context': {'lab_namespace': 'demo'}}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('LIFEAFTERCODE_MIM_CONFIG', str(path))
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setattr('shutil.which', lambda *a: 'sf')
    incident = {'Id': 'a00123456789014AAA', 'LastModifiedDate': NOW.isoformat(),
                'Service__c': 'SYNTHETIC-NETWORK', 'Summary__c': 'unrelated words', 'NodeKey__c': NODE}
    monkeypatch.setattr(mim, 'query_records', lambda *a: [incident])
    current = datetime.now(timezone.utc)
    calls = []
    def query(text):
        calls.append(text)
        return [observation(when=current)] if 'MIM_NetworkEvidence__c' in text else [contract()]
    monkeypatch.setattr(mim, 'query_salesforce', query)
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 50000))
    headers = {'Origin': 'http://localhost', 'X-LifeAfterCode-Release': '1'}
    response = client.post('/api/mim/recommend', json={'record_id': incident['Id']}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['recommendation']['recommended_dip_id'] == 'BFD'
    assert response.json()['evidence']['record_id'] == incident['Id']
    assert len(calls) == 2
    monkeypatch.setenv('LIFEAFTERCODE_SF_PARENT_ORIGINS', 'https://demo.lightning.force.com')
    hosted = client.post('/api/mim/advise-snapshot', headers=headers,
                         json={'object': config['incident']['object'], 'record': incident})
    assert hosted.status_code == 409


def test_incomplete_salesforce_query_is_not_used(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('shutil.which', lambda *a: 'sf')
    monkeypatch.setattr(mim.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({'status': 0, 'result': {'records': [], 'done': False}})))
    with pytest.raises(HTTPException) as error:
        mim.query_salesforce('SELECT Id FROM MIM_DIP__c')
    assert error.value.status_code == 502


def test_context_config_rejects_query_expressions_and_missing_service():
    with pytest.raises(ValueError):
        NetworkContext(lab_namespace="demo' OR Name != ''")
    with pytest.raises(ValueError):
        NetworkContext(lab_namespace='demo', evidence_object='Account WHERE Name != null')
    with pytest.raises(HTTPException):
        evaluate_context(SETTINGS, NODE, '', [observation()], [contract()], now=NOW)
