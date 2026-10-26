"""The simplified runner reuses review/export and the existing deployment playbook."""
import zipfile

import pytest

from app.reviewed_metadata import (
    ReviewedCanonicalPlan, ReviewedEntity, ReviewedField, export_reviewed_metadata,
)
import run
import scripts.salesforce_deploy_playbook as playbook


def reviewed_zip(tmp_path, extra=None, change_metadata=False, approved=True):
    plan = ReviewedCanonicalPlan(repository='legacy.zip', repository_id='source-hash', entities=[
        ReviewedEntity(concept='Incident', source_representations=['Incident'],
                       evidence=['models.py:2'], status='approved', fields=[
                           ReviewedField(source='Incident.ticket', target='Ticket',
                                         evidence='models.py:3', status='approved')]),
    ])
    source = tmp_path / 'source'
    export_reviewed_metadata(plan, source)
    if not approved:
        plan.entities[0].fields[0].status = 'review'
    archive = tmp_path / 'reviewed.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('canonical-review.json', plan.model_dump_json())
        for file in source.rglob('*'):
            if file.is_file():
                content = file.read_bytes()
                if change_metadata and file.name.endswith('field-meta.xml'):
                    content = content.replace(b'<length>255</length>', b'<length>200</length>')
                bundle.writestr(file.relative_to(source).as_posix(), content)
        if extra:
            bundle.writestr(extra, 'not approved')
    return archive


def test_validation_is_the_default_and_uses_existing_playbook(tmp_path, monkeypatch):
    archive = reviewed_zip(tmp_path)
    calls = []
    monkeypatch.setattr(run.shutil, 'which', lambda _: 'sf')
    monkeypatch.setattr(playbook, 'main', lambda args: calls.append(args))
    run.main(['salesforce', '--metadata-zip', str(archive)])
    assert len(calls) == 1
    assert '--validate-only' in calls[0]
    assert '--approve' not in calls[0]
    assert calls[0][calls[0].index('--org') + 1] == 'hackfest-developer'


def test_approved_release_validates_before_deploying_and_assigns_only_when_requested(tmp_path, monkeypatch):
    archive = reviewed_zip(tmp_path)
    calls = []
    monkeypatch.setattr(run.shutil, 'which', lambda _: 'sf')
    monkeypatch.setattr(playbook, 'main', lambda args: calls.append(args))
    run.main(['salesforce', '--metadata-zip', str(archive), '--approve', '--assign-to-current-user'])
    assert len(calls) == 2
    assert '--validate-only' in calls[0]
    assert '--approve' in calls[1]
    assert '--assign-to-current-user' in calls[1]


def test_failed_validation_stops_before_deployment(tmp_path, monkeypatch):
    archive = reviewed_zip(tmp_path)
    calls = []
    monkeypatch.setattr(run.shutil, 'which', lambda _: 'sf')
    def fail(args):
        calls.append(args)
        raise RuntimeError('Salesforce rejected validation')
    monkeypatch.setattr(playbook, 'main', fail)
    with pytest.raises(RuntimeError, match='rejected validation'):
        run.main(['salesforce', '--metadata-zip', str(archive), '--approve'])
    assert len(calls) == 1
    assert '--validate-only' in calls[0]


@pytest.mark.parametrize('options', [
    {'extra': '../outside.xml'}, {'extra': 'unapproved.xml'},
    {'change_metadata': True}, {'approved': False},
])
def test_modified_or_unapproved_bundles_are_rejected_before_cli(tmp_path, monkeypatch, options):
    archive = reviewed_zip(tmp_path, **options)
    monkeypatch.setattr(run.shutil, 'which', lambda _: pytest.fail('Must reject before CLI discovery'))
    with pytest.raises(ValueError):
        run.main(['salesforce', '--metadata-zip', str(archive), '--approve'])
    assert not (tmp_path / 'outside.xml').exists()


def test_local_launch_uses_discovery_app_and_explicit_workspace(tmp_path, monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setenv('MAPPER_WORKSPACE', '')
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '0')
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    run.main(['serve', '--workspace', str(tmp_path), '--port', '8123'])
    assert run.os.environ['MAPPER_WORKSPACE'] == str(tmp_path.resolve())
    assert run.os.environ['LIFEAFTERCODE_BROWSER_DEPLOY'] == '1'
    assert calls == [(('app.main:app',), {'host': '127.0.0.1', 'port': 8123, 'reload': False, 'proxy_headers': True, 'forwarded_allow_ips': '127.0.0.1,::1'})]


def test_frontend_flag_is_reused_for_both_validation_and_deployment(tmp_path, monkeypatch):
    archive = reviewed_zip(tmp_path)
    calls = []
    monkeypatch.setattr(run.shutil, 'which', lambda _: 'sf')
    monkeypatch.setattr(playbook, 'main', lambda args: calls.append(args))
    run.main(['salesforce', '--metadata-zip', str(archive), '--frontend-url', 'https://mim.example/alexa', '--approve'])
    assert len(calls) == 2
    assert all(args[args.index('--frontend-url') + 1] == 'https://mim.example/alexa' for args in calls)
