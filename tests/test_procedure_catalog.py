import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.procedure_catalog import read_procedure_catalogs
from app.canonical_entities import group_canonical_entities
from app.contract_classification import ClassifiedModel


def procedure(identifier, key='dip_id'):
    return {key: identifier, 'title': 'Inspect BFD session', 'service': 'SYNTHETIC-NETWORK',
            'implementation_steps': ['Collect session state', 'Review peer timers'],
            'validation_steps': ['Reobserve the signal'], 'rollback_steps': ['No change executed'],
            'provenance': {'kind': 'synthetic'}, 'execution_enabled': False}


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('repo/data/dips.json', json.dumps([procedure('DIP-1')]))
        bundle.writestr('repo/data/mops.json', json.dumps([procedure('MOP-1')]))
        bundle.writestr('repo/data/sops.json', json.dumps({'sops': [procedure('SOP-1', 'sop_id')]}))
    return output.getvalue()


def test_all_procedure_variants_share_one_existing_canonical_identity():
    models = [ClassifiedModel(name=name, source_file=name+'.py', role='business_entity_candidate')
              for name in ['DIP', 'NetworkMOP', 'SOP', 'RemediationProcedure', 'RecoveryRunbook']]
    groups = group_canonical_entities(models)
    assert len(groups) == 1
    assert groups[0].concept == 'DIP'
    assert len(groups[0].representations) == 5
    assert groups[0].status == 'review'


def test_json_catalogs_reach_salesforce_review_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path))
    monkeypatch.setattr('app.main.DATA', tmp_path)
    client = TestClient(app)
    scanned = client.post('/api/analyze', files={'file': ('procedures.zip', archive())})
    assert scanned.status_code == 200, scanned.text
    project = scanned.json()['project_id']
    base = f'/api/projects/{project}/canonical'
    result = client.get(base+'/candidates').json()
    catalogs = result['procedure_catalogs']
    assert {c['procedure_type'] for c in catalogs} == {'DIP', 'MOP', 'SOP'}
    assert sum(len(c['records']) for c in catalogs) == 3
    plan = result['review_plan']
    assert [entity['concept'] for entity in plan['entities']] == ['DIP']
    entity = plan['entities'][0]
    assert entity['status'] == 'review'
    assert len([f for f in entity['fields'] if f['source'].endswith('.implementation_steps')]) == 1
    steps = next(f for f in entity['fields'] if f['source'].endswith('.implementation_steps'))
    assert steps['data_type'] == 'LongTextArea'
    assert '#/0/implementation_steps' in steps['evidence']
    assert client.get(base+'/metadata.zip').status_code == 409
    entity['status'] = 'approved'
    steps['status'] = 'approved'
    saved = client.put(base+'/review', json=plan)
    assert saved.status_code == 200, saved.text
    metadata = client.get(base+'/metadata.zip')
    assert metadata.status_code == 200
    with zipfile.ZipFile(io.BytesIO(metadata.content)) as bundle:
        fields = [n for n in bundle.namelist() if n.endswith('.field-meta.xml')]
        assert len(fields) == 1
        assert '_DIP__c/' in fields[0]
        assert '<type>LongTextArea</type>' in bundle.read(fields[0]).decode()
        obj = next(n for n in bundle.namelist() if n.endswith('.object-meta.xml'))
        assert '<label>Procedure</label>' in bundle.read(obj).decode()
    steps['evidence'] = 'forged.json#/0/implementation_steps'
    assert client.put(base+'/review', json=plan).status_code == 400


def test_catalogs_require_real_structured_steps_and_preserve_records():
    raw = procedure('SOP-2', 'sop_id')
    catalogs, warnings = read_procedure_catalogs([('sops.json', json.dumps([raw, {'sop_id': 'BAD'}]))])
    assert warnings
    record = catalogs[0]['records'][0]
    assert record['record'] == raw
    assert record['procedure_type'] == 'SOP'
    assert next(f for f in catalogs[0]['fields'] if f['key'] == 'implementation_steps')['reference'] == '/0/implementation_steps'


def test_existing_saved_review_gets_new_unapproved_procedure_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv('MAPPER_WORKSPACE', str(tmp_path))
    monkeypatch.setattr('app.main.DATA', tmp_path)
    client = TestClient(app)
    scan = client.post('/api/analyze', files={'file': ('procedures.zip', archive())}).json()
    project = scan['project_id']
    base = f'/api/projects/{project}/canonical'
    initial = client.get(base+'/candidates').json()['review_plan']
    initial['entities'] = []
    assert client.put(base+'/review', json=initial).status_code == 200
    merged = client.get(base+'/candidates').json()
    assert not merged['review_saved']
    assert merged['review_plan']['entities'][0]['status'] == 'review'
