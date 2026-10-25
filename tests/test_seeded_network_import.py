import json

import pytest

from app.seeded_network_import import discover, plan, digest, schema_review, write_field_proposals
from scripts import seeded_network_sf as cli


def fixtures(tmp_path):
    dip = {'dip_id': 'LAB-MOP-BFD', 'title': 'BFD Session Down', 'service': 'SYNTHETIC-NETWORK',
           'category': 'bfd', 'contract_version': '1', 'execution_enabled': False,
           'provenance': {'kind': 'synthetic'}}
    (tmp_path / 'synthetic_network_mops.json').write_text(json.dumps([dip]))
    row = {'device_id': 'NODE-00001', 'peer_id': 'NODE-00002', 'simulation_only': True,
           'observed_at': '2026-10-25T00:00:00Z', 'sample': {'bfd_state': 'down'}}
    (tmp_path / 'network-export.json').write_text(json.dumps({'simulation_only': True, 'nodes': [row]}))
    return dip, row


def description(batch):
    fields = {field for row in batch['rows'] for field in row}
    return {'createable': True, 'updateable': True, 'fields': [
        {'name': field, 'type': 'textarea' if field.endswith('JSON__c') else 'string',
         'length': 131072, 'createable': True, 'updateable': True,
         'externalId': field == batch['external_id'], 'unique': field == batch['external_id']}
        for field in fields]}


def test_reimports_use_existing_catalog_identity_and_link_observations(tmp_path):
    dip, _ = fixtures(tmp_path)
    discovered = discover(tmp_path, 'lab-one')
    assert {r['kind'] for r in discovered['records']} == {'node', 'observation', 'dip'}
    value = plan(discovered)
    catalog = next(b for b in value['batches'] if b['object'] == 'MIM_DIP__c')
    assert catalog['rows'][0]['CatalogKey__c'] == digest({'dip_id': dip['dip_id'], 'version': '1'})
    assert catalog['rows'][0]['CatalogReviewStatus__c'] == 'needs_review'
    evidence = next(b for b in value['batches'] if b['object'] != 'MIM_DIP__c')
    node = next(r for r in evidence['rows'] if r['EvidenceKind__c'] == 'node')
    observation = next(r for r in evidence['rows'] if r['EvidenceKind__c'] == 'observation')
    assert observation['NodeKey__c'] == node['SourceKey__c']
    assert plan(discover(tmp_path, 'lab-one')) == value
    assert plan(discover(tmp_path, 'other-lab'))['review_digest'] != value['review_digest']


def test_new_observation_retains_history_with_same_node_key(tmp_path):
    _, row = fixtures(tmp_path)
    first = discover(tmp_path, 'lab')
    row['observed_at'] = '2026-10-25T01:00:00Z'
    row['sample']['bfd_state'] = 'up'
    (tmp_path / 'network-export.json').write_text(json.dumps({'simulation_only': True, 'nodes': [row]}))
    second = discover(tmp_path, 'lab')
    def keys(data, kind):
        return next(r['key'] for r in data['records'] if r['kind'] == kind)
    assert keys(first, 'node') == keys(second, 'node')
    assert keys(first, 'observation') != keys(second, 'observation')


def test_command_templates_are_not_observations_and_code_never_executes(tmp_path):
    (tmp_path / 'generator.py').write_text("raise RuntimeError('must not execute')")
    (tmp_path / 'network_command_fixtures.json').write_text(json.dumps({'profile': 'test', 'commands': {
        'bfd': {'command': 'show bfd', 'platform': 'fixture', 'outputs': {'down': 'Down'}}}}))
    result = discover(tmp_path, 'lab')
    assert [r['kind'] for r in result['records']] == ['command_fixture']
    assert result['records'][0]['payload']['template_only']
    assert result['warnings']


def test_conflicts_and_unmarked_network_data_rejected(tmp_path):
    dip, row = fixtures(tmp_path)
    (tmp_path / 'synthetic_network_mops.json').write_text(json.dumps([dip, dict(dip, title='changed')]))
    with pytest.raises(ValueError, match='Conflicting'):
        discover(tmp_path, 'lab')
    (tmp_path / 'synthetic_network_mops.json').unlink()
    row['simulation_only'] = False
    (tmp_path / 'network-export.json').write_text(json.dumps({'simulation_only': True, 'nodes': [row]}))
    with pytest.raises(ValueError, match='simulation_only'):
        discover(tmp_path, 'lab')


def test_schema_reuse_proposes_missing_fields_and_blocks_unsafe_keys(tmp_path):
    fixtures(tmp_path)
    batch = plan(discover(tmp_path, 'lab'))['batches'][0]
    desc = description(batch)
    assert schema_review(batch, desc) == {'object': batch['object'], 'missing_fields': [], 'blockers': []}
    desc['fields'] = [f for f in desc['fields'] if f['name'] != 'ContractJSON__c']
    review = schema_review(batch, desc)
    assert review['missing_fields'][0]['type'] == 'LongTextArea'
    write_field_proposals(review, tmp_path / 'metadata')
    assert len(list((tmp_path / 'metadata').rglob('*.xml'))) == 1
    next(f for f in desc['fields'] if f['name'] == batch['external_id'])['unique'] = False
    assert schema_review(batch, desc)['blockers']


def test_import_preflights_all_objects_and_requires_approval(tmp_path, monkeypatch):
    fixtures(tmp_path)
    value = plan(discover(tmp_path, 'lab'))
    calls = []
    def run(executable, *args):
        calls.append(args)
        if args[:2] == ('sobject', 'describe'):
            return description(next(b for b in value['batches'] if b['object'] == args[args.index('--sobject')+1]))
        batch = next(b for b in value['batches'] if b['object'] == args[args.index('--sobject')+1])
        with open(args[args.index('--file')+1]) as stream:
            assert batch['external_id'] in stream.readline()
        return {'jobInfo': {'id': 'JOB', 'state': 'JobComplete', 'numberRecordsFailed': 0, 'numberRecordsProcessed': len(batch['rows'])}}
    monkeypatch.setattr(cli, 'run_sf', run)
    with pytest.raises(ValueError, match='approval'):
        cli.apply(value, 'wrong', 'sf')
    assert not calls
    receipts = cli.apply(value, value['review_digest'], 'sf')
    assert len(receipts) == 2
    assert calls[0][:2] == calls[1][:2] == ('sobject', 'describe')
    assert all('hackfest-developer' in args for args in calls)
    assert all(args[:3] == ('data', 'upsert', 'bulk') for args in calls[2:])


def test_partial_bulk_job_never_claimed_success(tmp_path, monkeypatch):
    fixtures(tmp_path)
    value = plan(discover(tmp_path, 'lab'))
    monkeypatch.setattr(cli, 'preflight', lambda *a: [])
    monkeypatch.setattr(cli, 'run_sf', lambda *a: {'jobInfo': {'id': 'JOB', 'state': 'JobComplete', 'numberRecordsFailed': 1}})
    with pytest.raises(RuntimeError, match='incomplete'):
        cli.apply(value, value['review_digest'], 'sf')


def test_plan_tampering_rejected(tmp_path):
    fixtures(tmp_path)
    value = plan(discover(tmp_path, 'lab'))
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(value))
    assert cli.load_plan(path) == value
    value['batches'][0]['rows'][0]['Title__c'] = 'changed'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='digest'):
        cli.load_plan(path)


def test_repository_scan_includes_large_catalog_with_bounded_seed_exception(tmp_path):
    import zipfile
    from app.discovery_inventory import build_discovery_inventory
    dip, _ = fixtures(tmp_path)
    dip['implementation_steps'] = ['x' * 1600]
    records = [dict(dip, dip_id=f'LAB-{index}') for index in range(200)]
    encoded = json.dumps(records)
    assert len(encoded) > 300000
    archive = tmp_path / 'repository.zip'
    # Stored data avoids the archive compression-ratio guard, which remains active.
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('data/synthetic_network_mops.json', encoded)
    found = build_discovery_inventory(archive)['seeded_network']
    assert len(found['records']) == 200
    assert all(row['provenance'] == 'synthetic' for row in found['records'])


def test_mops_alias_uses_existing_seed_discovery(tmp_path):
    fixtures(tmp_path)
    (tmp_path / 'synthetic_network_mops.json').rename(tmp_path / 'mops.json')
    result = discover(tmp_path, 'lab')
    assert sum(row['kind'] == 'dip' for row in result['records']) == 1
    assert next(row for row in result['records'] if row['kind'] == 'dip')['source_file'] == 'mops.json'
