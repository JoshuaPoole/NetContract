"""Evidence-backed, static repository discovery. Uploaded code is never executed."""
import ast
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from .container_discovery import discover_container_definitions, is_dockerfile
from .schema_relationships import analyze_schema_relationships
from .mongodb_relationships import analyze_mongodb_relationships

MAX_ARCHIVE_BYTES = 20_000_000
MAX_FILES = 800
MAX_ENTRY_BYTES = 300_000
MAX_TOTAL_UNCOMPRESSED = 30_000_000
SOURCE_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx'}
CONFIG_SUFFIXES = {'.json', '.yaml', '.yml', '.tf', '.toml'}
SKIP_PARTS = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__', '.next'}
PERSISTENCE_PACKAGES = {'pymongo', 'motor', 'mongoengine', 'sqlalchemy', 'psycopg2', 'psycopg', 'sqlite3', 'redis', 'boto3', 'mysql', 'mysqlclient', 'asyncmy'}
OPERATIONS = {'find', 'find_one', 'insert_one', 'insert_many', 'update_one', 'update_many', 'delete_one', 'delete_many', 'aggregate', 'rpush', 'lpush', 'blpop', 'brpop', 'llen', 'execute', 'commit', 'query', 'add', 'flush'}
INFRA_NAMES = {'dockerfile', 'docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml', 'requirements.txt', 'pyproject.toml', 'package.json', 'terraform.tf', 'serverless.yml'}
DEPENDENCY_HINTS = re.compile(r'\b(?:from\s+["\']([^"\']+)["\']|require\s*\(\s*["\']([^"\']+)["\']\s*\)|import\s*\(\s*["\']([^"\']+)["\']\s*\))')

def _finding(filename, line=None, **kwargs):
    result = {'source_file': filename, 'evidence_type': 'static'}
    if line is not None:
        result['line'] = line
    result.update(kwargs)
    return result

def _read_entries(archive):
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 20 MB')
    total = 0
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError('Archive has too many entries')
        for info in infos:
            name = info.filename.replace('\\', '/')
            path = PurePosixPath(name)
            if info.is_dir() or name.startswith('/') or '..' in path.parts or any(p in SKIP_PARTS for p in path.parts):
                continue
            limit = 10_000_000 if path.name in {'synthetic_network_mops.json', 'dips.json', 'mops.json', 'sops.json', 'procedures.json', 'runbooks.json', 'network_command_fixtures.json', 'network-export.json'} else MAX_ENTRY_BYTES
            if info.file_size > limit or info.file_size < 0:
                continue
            if info.compress_size == 0 and info.file_size > 0:
                continue
            if info.compress_size and info.file_size / info.compress_size > 100:
                continue
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError('Archive exceeds safe uncompressed scan budget')
            if path.suffix.lower() not in SOURCE_SUFFIXES | CONFIG_SUFFIXES and path.name.lower() not in INFRA_NAMES and not is_dockerfile(name):
                continue
            try:
                yield name, z.read(info).decode('utf-8', errors='replace')
            except (RuntimeError, ValueError, zipfile.BadZipFile):
                continue

def _entity_hint(call, function):
    """Conservative syntax-only entity hint; never evaluates repository code."""
    if call.func.attr == 'query' and call.args:
        arg = call.args[0]
        if isinstance(arg, (ast.Name, ast.Attribute)):
            return ast.unparse(arg), 'query_argument'
    if call.func.attr != 'add' or not call.args or function is None:
        return None, None
    arg = call.args[0]
    if not isinstance(arg, ast.Name):
        return None, None
    assignments = []
    for stmt in ast.walk(function):
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.lineno < call.lineno:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(isinstance(t, ast.Name) and t.id == arg.id for t in targets):
                value = stmt.value
                if isinstance(value, ast.Call) and isinstance(value.func, (ast.Name, ast.Attribute)):
                    assignments.append((stmt.lineno, ast.unparse(value.func)))
    if assignments:
        return max(assignments)[1], 'local_constructor_assignment'
    return None, None

def discover_repository(archive: Path) -> dict:
    archive = Path(archive)
    m = {'schema_version': '3.1', 'repository': archive.name,
         'functions': [], 'classes': [], 'imports': [], 'contract_usages': [],
         'persistence_dependencies': [], 'persistence_operations': [],
         'api_endpoints': [], 'json_contracts': [], 'js_dependencies': [],
         'infrastructure': [], 'warnings': [],
         'assessment': {'status': 'not_assessed', 'reason': 'Requires separate suitability review'}}
    entries = list(_read_entries(archive))
    m['container_definitions'] = [item.model_dump() for item in discover_container_definitions(entries)]
    m['schema_relationships'] = analyze_schema_relationships(entries)
    m['mongodb_relationships'] = analyze_mongodb_relationships(entries)
    scanned = 0
    for filename, source in entries:
        scanned += 1
        p = PurePosixPath(filename)
        suffix = p.suffix.lower()
        base = p.name.lower()
        if base in INFRA_NAMES or is_dockerfile(filename) or suffix == '.tf' or '/.github/workflows/' in '/' + filename:
            m['infrastructure'].append(_finding(filename, kind=('terraform' if suffix == '.tf' else base)))
        if suffix == '.json':
            try:
                value = json.loads(source)
                if base == 'package.json' and isinstance(value, dict):
                    for group in ('dependencies', 'devDependencies'):
                        for name in value.get(group, {}) if isinstance(value.get(group, {}), dict) else {}:
                            m['js_dependencies'].append(_finding(filename, package=name, declared_in=group))
                elif isinstance(value, list) and value and isinstance(value[0], dict):
                    m['json_contracts'].append(_finding(filename, shape='list_of_objects', record_count=len(value), fields=[{'name': k, 'observed_type': type(v).__name__} for k,v in value[0].items()], sample_only=True))
                elif isinstance(value, dict) and base != 'package.json':
                    m['json_contracts'].append(_finding(filename, shape='object', fields=[{'name': k, 'observed_type': type(v).__name__} for k,v in value.items()], sample_only=True))
            except (ValueError, UnicodeError):
                m['warnings'].append('Invalid JSON: ' + filename)
        if suffix in {'.js', '.jsx', '.ts', '.tsx'}:
            for n, line in enumerate(source.splitlines(), 1):
                for match in DEPENDENCY_HINTS.finditer(line):
                    m['js_dependencies'].append(_finding(filename, n, package=next(x for x in match.groups() if x), declared_in='source_import'))
        if suffix != '.py':
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            m['warnings'].append('Could not parse Python: ' + filename)
            continue
        scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        def enclosing_scope(node, kinds):
            matches = [s for s in scopes if isinstance(s, kinds) and s.lineno <= node.lineno <= getattr(s, 'end_lineno', s.lineno)]
            return min(matches, key=lambda s: (getattr(s, 'end_lineno', s.lineno) - s.lineno, -s.lineno), default=None)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m['functions'].append(_finding(filename, node.lineno, name=node.name))
                for decorator in node.decorator_list:
                    expr = ast.unparse(decorator)
                    if re.search(r'\.(?:get|post|put|delete|patch)\s*\(', expr):
                        m['api_endpoints'].append(_finding(filename, node.lineno, function=node.name, decorator=expr))
            elif isinstance(node, ast.ClassDef):
                m['classes'].append(_finding(filename, node.lineno, name=node.name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if node.module else [])
                for name in names:
                    m['imports'].append(_finding(filename, node.lineno, module=name))
                    if name.split('.')[0] in PERSISTENCE_PACKAGES:
                        m['persistence_dependencies'].append(_finding(filename, node.lineno, package=name))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in OPERATIONS:
                function = enclosing_scope(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                owner = enclosing_scope(node, (ast.ClassDef,))
                receiver = ast.unparse(node.func.value)[:160]
                entity, entity_evidence = _entity_hint(node, function)
                m['persistence_operations'].append(_finding(filename, node.lineno, operation=node.func.attr, expression=ast.unparse(node.func)[:160], receiver=receiver, entity_hint=entity, entity_evidence=entity_evidence, function=function.name if function else None, class_name=owner.name if owner else None, classification='candidate'))
    m['scan_summary'] = {'files_inspected': scanned, 'static_only': True}
    m['warnings'].append('Candidate operations and JSON field types require manual verification; no runtime data flow is proven')
    return m



