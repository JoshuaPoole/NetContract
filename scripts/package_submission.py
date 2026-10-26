"""Build the discovery/Salesforce submission without historical demo workers."""
import argparse
import ast
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ('app/main.py', 'run.py', 'scripts/salesforce_deploy_playbook.py')
STATIC_FILES = (
    'README.md', 'requirements.txt', '.gitignore', 'app/index.html',
    'app/salesforce.html', 'app/assets/discovery.css', 'app/assets/common.js',
    'app/assets/discovery.js', 'app/assets/salesforce-review.js', 'app/assets/salesforce-deploy.js',
    'sfdx-project.json', 'docs/SALESFORCE_PLAYBOOK.md', 'docs/IMPLEMENTATION.md',
    'tests/test_procedure_catalog.py', 'docs/PROCEDURES.md', 'docs/BUILDER_RECORD_SYNC.md', 'docs/ALEX_WORKSPACE.md', 'docs/JUDGE_HOSTING.md', 'scripts/configure_judge_access.py', 'tests/test_judge_access.py', 'app/alex.html', 'app/assets/alex.js', 'app/assets/alexa.css', 'data/network_command_fixtures.json', 'data/node_lab.json', 'tests/test_node_investigation.py', 'tests/test_alex_workspace.py', 'tests/test_voice_workspace_ui.py', 'tests/test_published_workspace.py', 'tests/test_procedure_sync.py',
    'docs/SEED_IMPORT.md', 'scripts/seeded_network_sf.py', 'tests/test_seeded_network_import.py',
    'docs/MIM_NETWORK_DECISIONS.md', 'tests/test_mim_network_context.py',
    'docs/MIM_WORKSPACE.md', 'docs/MIM_INCIDENTS.md', 'app/mim.html',
    'app/assets/mim-incidents.js', 'tests/test_mim_incidents.py',
    'scripts/package_submission.py', 'tests/test_discovery_inventory.py',
    'tests/test_terraform_inventory.py', 'tests/test_submission_package.py',
    'tests/test_run_workflow.py', 'tests/test_salesforce_browser.py',
    'tests/test_salesforce_deploy_playbook.py',
    'scripts/salesforce_workspace/reader.cls', 'scripts/salesforce_workspace/readerTest.cls',
    'scripts/salesforce_workspace/workspace.html', 'scripts/salesforce_workspace/workspace.js',
    'scripts/salesforce_workspace/workspace.css', 'scripts/salesforce_workspace/workspace.js-meta.xml',
)
EXCLUDED_MODULES = {
    'worker_graph', 'mim_app_reconstruction', 'reconstructed_app_api',
    'reconstructed_mim', 'reconstruction_rehearsal', 'alexa_demo',
    'alexa_mcp', 'alexa_simulation', 'synthetic_network', 'network_engineer_demo',
}


def runtime_files(root=ROOT):
    """Follow Python imports from the entrypoints, including local imports."""
    pending, found = list(SEEDS), set(STATIC_FILES)
    inspected = set()
    while pending:
        name = pending.pop()
        if name in inspected:
            continue
        inspected.add(name)
        source = root / name
        if not source.is_file():
            raise ValueError(f'Missing submission dependency: {name}')
        if source.stem in EXCLUDED_MODULES:
            raise ValueError(f'Discovery runtime unexpectedly depends on workers: {name}')
        found.add(name)
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8'))):
            modules = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level != 1:
                        raise ValueError(f'Unsupported relative import in {name}')
                    base = str(Path(name).parent).replace('/', '.')
                    modules = [base + '.' + node.module] if node.module else [
                        base + '.' + alias.name for alias in node.names]
                elif node.module:
                    modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module.startswith(('app.', 'scripts.')):
                    dependency = module.replace('.', '/') + '.py'
                    pending.append(dependency)
        if name.startswith('app/'):
            found.add('app/__init__.py')
    return sorted(found)


def package(destination, root=ROOT):
    """Write only the enumerated dependency closure, with a reviewable manifest."""
    files = runtime_files(root)
    manifest = {
        'product': 'LifeAfterCode DevOps',
        'source_commit': 'e18c198914e2480f0fd91c47b5196ec708197554',
        'scope': 'Static business contracts, Terraform inventory, reviewed Salesforce metadata',
        'excluded': sorted(EXCLUDED_MODULES), 'files': files,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            content = (root / name).read_bytes()
            if name == 'requirements.txt':
                content = b'\n'.join(line for line in content.splitlines()
                                     if not line.startswith(b'mcp==')) + b'\n'
            bundle.writestr(name, content)
        bundle.writestr('submission-manifest.json', json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/lifeaftercode-submission.zip')
    arguments = parser.parse_args()
    result = package(arguments.output)
    print(f'Packaged {len(result["files"])} files into {arguments.output}')

