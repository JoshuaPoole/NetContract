"""Offline regression tests for the Salesforce playbook's generic permission generation."""
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "salesforce_deploy_playbook.py"
spec = importlib.util.spec_from_file_location("contractcyber_playbook", SCRIPT)
playbook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(playbook)


def test_generates_permissions_for_arbitrary_objects_in_salesforce_order(tmp_path):
    objects = {
        "R123_Pricing__c": ["Amount__c", "Currency__c"],
        "R456_Orders__c": ["Reference__c"],
    }
    name = playbook.generate_permissions(objects, tmp_path)
    root = ET.parse(tmp_path / f"{name}.permissionset-meta.xml").getroot()
    ns = {"s": playbook.SFNS}
    children = list(root)
    object_nodes = root.findall("s:objectPermissions", ns)
    field_nodes = root.findall("s:fieldPermissions", ns)
    assert len(object_nodes) == 2
    assert len(field_nodes) == 3
    assert max(map(children.index, object_nodes)) < min(map(children.index, field_nodes))
    assert {node.findtext("s:object", namespaces=ns) for node in object_nodes} == set(objects)
    assert all(node.findtext("s:allowDelete", namespaces=ns) == "false" for node in object_nodes)
    assert all(node.findtext("s:modifyAllRecords", namespaces=ns) == "false" for node in object_nodes)
    assert all(node.findtext("s:editable", namespaces=ns) == "true" for node in field_nodes)
    assert playbook.generate_permissions(objects, tmp_path) == name


def test_verification_fails_for_invisible_fields(monkeypatch):
    monkeypatch.setattr(playbook, "run_sf", lambda *a, **kw: {"fields": [{"name": "Name", "createable": True}]})
    with pytest.raises(RuntimeError, match="missing or not createable"):
        playbook.verify_fields("sf", "test", {"R123_Pricing__c": ["Amount__c"]})


def test_verification_passes_for_visible_createable_fields(monkeypatch):
    monkeypatch.setattr(playbook, "run_sf", lambda *a, **kw: {
        "fields": [{"name": "Amount__c", "createable": True}],
    })
    playbook.verify_fields("sf", "test", {"R123_Pricing__c": ["Amount__c"]})


def test_lightning_app_tabs_and_visibility_match_scoped_objects(tmp_path):
    objects = {"R123_DIP__c": ["Status__c"], "R123_Incident__c": ["Summary__c"]}
    name = playbook.generate_permissions(objects, tmp_path / "permissionsets")
    app = playbook.generate_lightning_app(objects, tmp_path, name, "MIM & DIP")
    ns = {"s": playbook.SFNS}
    root = ET.parse(tmp_path / "applications" / f"{app}.app-meta.xml").getroot()
    assert root.findtext("s:label", namespaces=ns) == "MIM & DIP"
    assert {item.text for item in root.findall("s:tabs", ns)} == set(objects)
    permissions = ET.parse(tmp_path / "permissionsets" / f"{name}.permissionset-meta.xml").getroot()
    assert permissions.findtext("s:applicationVisibilities/s:application", namespaces=ns) == app
    assert {item.findtext("s:tab", namespaces=ns) for item in permissions.findall("s:tabSettings", ns)} == set(objects)
    assert len(list((tmp_path / "tabs").glob("*.tab-meta.xml"))) == 2


def test_validate_only_never_assigns_or_verifies(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(playbook.shutil, "which", lambda _: "sf")
    monkeypatch.setattr(playbook, "inspect_objects", lambda _: {"DIP__c": ["Status__c"]})
    source = tmp_path / "objects" / "DIP__c"
    source.mkdir(parents=True)
    monkeypatch.setattr(playbook.sys, "argv", ["playbook", "--objects-dir", str(source.parent), "--validate-only", "--app-label", "Reviewed MIM"])
    def run(*args, **kwargs):
        calls.append(args)
        return {"status": "Succeeded", "id": "check-only"}
    monkeypatch.setattr(playbook, "run_sf", run)
    monkeypatch.setattr(playbook, "verify_fields", lambda *args: pytest.fail("validation must not verify deployed fields"))
    playbook.main()
    assert len(calls) == 1
    assert "--dry-run" in calls[0]
    assert "permset" not in calls[0]


@pytest.mark.parametrize("flags", [
    ["--validate-only", "--approve"],
    ["--validate-only", "--assign-to-current-user"],
    ["--verify-only", "--assign-to-current-user"],
])
def test_conflicting_modes_fail_before_cli(monkeypatch, flags):
    monkeypatch.setattr(playbook.sys, "argv", ["playbook", "--objects-dir", "unused", *flags])
    monkeypatch.setattr(playbook.shutil, "which", lambda _: pytest.fail("must fail before CLI discovery"))
    with pytest.raises(SystemExit):
        playbook.main()



@pytest.mark.parametrize('validate_only', [True, False])
def test_windows_locked_temp_folder_does_not_replace_salesforce_success(tmp_path, monkeypatch, validate_only):
    real_temporary_directory = playbook.tempfile.TemporaryDirectory
    cleanup_settings = []

    class LockedTemporaryDirectory:
        def __init__(self, *args, ignore_cleanup_errors=False, **kwargs):
            self.folder = real_temporary_directory(*args, **kwargs)
            self.ignore = ignore_cleanup_errors
        def __enter__(self):
            return self.folder.name
        def __exit__(self, *_):
            self.folder.cleanup()
            cleanup_settings.append(self.ignore)
            if not self.ignore:
                raise PermissionError(32, 'The process cannot access the file; another process is using it')
            return False

    monkeypatch.setattr(playbook.tempfile, 'TemporaryDirectory', LockedTemporaryDirectory)
    monkeypatch.setattr(playbook.shutil, 'which', lambda _: 'sf')
    source = tmp_path / 'objects' / 'Incident__c'
    source.mkdir(parents=True)
    monkeypatch.setattr(playbook, 'inspect_objects', lambda _: {'Incident__c': ['Ticket__c']})
    monkeypatch.setattr(playbook, 'run_sf', lambda *a, **k: {'status': 'Succeeded', 'id': 'confirmed-job'})
    verified = []
    monkeypatch.setattr(playbook, 'verify_fields', lambda *args: verified.append(args))
    flags = ['--validate-only'] if validate_only else ['--approve']
    playbook.main(['--objects-dir', str(source.parent), *flags])
    assert cleanup_settings == [True]
    assert len(verified) == (0 if validate_only else 1)


def test_best_effort_cleanup_does_not_hide_a_failed_salesforce_deployment(tmp_path, monkeypatch):
    source = tmp_path / 'objects' / 'Incident__c'
    source.mkdir(parents=True)
    monkeypatch.setattr(playbook.shutil, 'which', lambda _: 'sf')
    monkeypatch.setattr(playbook, 'inspect_objects', lambda _: {'Incident__c': ['Ticket__c']})
    monkeypatch.setattr(playbook, 'run_sf', lambda *a, **k: {'status': 'Failed', 'id': 'failed-job'})
    with pytest.raises(RuntimeError, match='not confirmed successful: Failed'):
        playbook.main(['--objects-dir', str(source.parent), '--validate-only'])


@pytest.mark.parametrize('url', [
    'http://mim.example/alexa', 'javascript:alert(1)',
    'https://user:password@mim.example/alexa', 'https://mim.example/alexa?token=secret',
    'https://mim.example/alexa#token', 'https://mim.example:99999/alexa',
])
def test_frontend_url_rejects_insecure_or_credential_bearing_metadata(url):
    with pytest.raises(ValueError):
        playbook.normalize_frontend_url(url)


def test_workspace_reuses_hosted_frontend_and_preserves_existing_app_identity(tmp_path):
    objects = {'R7ac51ef9_Incident__c': ['Ticket__c']}
    name = playbook.generate_permissions(objects, tmp_path / 'permissionsets')
    app = playbook.generate_lightning_app(objects, tmp_path, name, 'LifeAfterCode', 'https://MIM.EXAMPLE:8443/alexa')
    ns = {'s': playbook.SFNS}
    root = ET.parse(tmp_path / 'applications' / f'{app}.app-meta.xml').getroot()
    tabs = [item.text for item in root.findall('s:tabs', ns)]
    assert app == name.removesuffix('_Access') + '_App'
    assert tabs[0] == name.removesuffix('_Access') + '_Workspace'
    assert tabs[1:] == list(objects)
    tab = ET.parse(tmp_path / 'tabs' / f'{tabs[0]}.tab-meta.xml').getroot()
    component = tab.findtext('s:lwcComponent', namespaces=ns)
    bundle = tmp_path / 'lwc' / component
    javascript = (bundle / f'{component}.js').read_text()
    assert 'https://mim.example:8443/alexa' in javascript
    assert '__FRONTEND_URL__' not in javascript
    assert 'src={frontendUrl}' in (bundle / f'{component}.html').read_text()
    assert 'Session_ID' not in javascript
    meta = ET.parse(bundle / f'{component}.js-meta.xml').getroot()
    assert meta.findtext('s:targets/s:target', namespaces=ns) == 'lightning__Tab'
    trusted_file, = (tmp_path / 'cspTrustedSites').glob('*.xml')
    trusted = ET.parse(trusted_file).getroot()
    assert trusted.findtext('s:endpointUrl', namespaces=ns) == 'https://mim.example:8443'
    assert trusted.findtext('s:isApplicableToFrameSrc', namespaces=ns) == 'true'
    assert trusted.findtext('s:isApplicableToConnectSrc', namespaces=ns) == 'false'
    permissions = ET.parse(tmp_path / 'permissionsets' / f'{name}.permissionset-meta.xml').getroot()
    assert tabs[0] in {item.findtext('s:tab', namespaces=ns) for item in permissions.findall('s:tabSettings', ns)}
    assert len(permissions.findall('s:objectPermissions', ns)) == 1
    assert len(permissions.findall('s:fieldPermissions', ns)) == 1


def test_assignment_failure_array_has_actionable_error(monkeypatch):
    import json
    from types import SimpleNamespace
    monkeypatch.setattr(playbook.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=json.dumps({'status': 1, 'result': {'failures': [{'name': 'demo-user', 'message': 'Permission set already assigned'}]}}), stderr=''))
    with pytest.raises(playbook.SalesforceCommandError, match='org assign permset.*already assigned'):
        playbook.run_sf('sf', 'org', 'assign', 'permset')
    playbook.assign_permissions('sf','hackfest-developer','ScopedAccess')


def test_real_assignment_failure_is_not_suppressed(monkeypatch):
    import json
    from types import SimpleNamespace
    monkeypatch.setattr(playbook.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=json.dumps({'status': 1, 'result': {'failures': [{'message': 'Insufficient access'}]}}), stderr=''))
    with pytest.raises(playbook.SalesforceCommandError, match='Insufficient access'):
        playbook.assign_permissions('sf','hackfest-developer','ScopedAccess')


def test_empty_cli_error_still_names_failed_stage(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(playbook.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='{"status":1,"result":{}}', stderr=''))
    with pytest.raises(playbook.SalesforceCommandError, match='org assign permset.*exit 1'):
        playbook.assign_permissions('sf','hackfest-developer','ScopedAccess')
