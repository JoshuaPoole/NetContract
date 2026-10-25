"""Validate the actual judge package excludes the development experiments."""
import zipfile

from scripts.package_submission import package


def test_focused_package_contains_runtime_and_salesforce_but_no_workers(tmp_path):
    destination = tmp_path / 'submission.zip'
    manifest = package(destination)
    with zipfile.ZipFile(destination) as bundle:
        names = set(bundle.namelist())
        assert {'app/main.py', 'app/business_discovery.py', 'app/terraform_inventory.py',
                'app/canonical_project_api.py', 'scripts/salesforce_deploy_playbook.py',
                'submission-manifest.json'} <= names
        assert all(not any(word in name for word in ('reconstruct', 'worker_graph', 'alexa_', 'network_engineer', 'synthetic_network')) for name in names)
        assert b'mcp==' not in bundle.read('requirements.txt')
        assert names == set(manifest['files']) | {'submission-manifest.json'}
