"""Static MongoDB collection and MCP contract evidence; never executes repository code."""
import ast
import re


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError):
        return None


def analyze_mongodb_relationships(entries):
    result = {'collections': [], 'configuration': [], 'document_relationships': [],
              'configuration_warnings': [], 'analysis_limits': [
                  'Static evidence only; runtime environment, database contents and external MCP configuration not verified.'
              ]}
    by_name = {}
    for filename, source in entries:
        if not filename.endswith('.py'):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'getenv' and node.args:
                    env = _literal(node.args[0]); default = _literal(node.args[1]) if len(node.args) > 1 else None
                    if isinstance(env, str) and env.startswith(('MONGODB_', 'USE_MONGO_MCP')):
                        result['configuration'].append({'variable': env, 'default': default, 'source_file': filename, 'line': node.lineno})
                if node.func.attr == 'call_tool' and node.args and _literal(node.args[0]) == 'find':
                    kwargs = {k.arg: k.value for k in node.keywords if k.arg}
                    arguments = kwargs.get('arguments')
                    if isinstance(arguments, ast.Dict):
                        fields = {_literal(k): v for k, v in zip(arguments.keys, arguments.values)}
                        collection = _literal(fields.get('collection')) if fields.get('collection') is not None else None
                        if isinstance(collection, str):
                            result['collections'].append({'name': collection, 'access': 'read', 'interface': 'mongodb_mcp', 'operation': 'find', 'source_file': filename, 'line': node.lineno})
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'database':
                collection = _literal(node.slice)
                if isinstance(collection, str):
                    by_name[(filename, collection)] = node.lineno
            if isinstance(node, ast.Dict):
                keys = [_literal(k) for k in node.keys]
                if 'incident_id' in keys:
                    for target, kind in (('dip_id', 'candidate_incident_to_dip'), ('kba_id', 'candidate_incident_to_kba')):
                        if target in keys:
                            result['document_relationships'].append({'kind': kind, 'field': target, 'source_file': filename, 'line': node.lineno, 'classification': 'candidate'})
    for (filename, collection), line in sorted(by_name.items()):
        result['collections'].append({'name': collection, 'access': 'write_candidate', 'interface': 'pymongo', 'operation': 'database_subscript', 'source_file': filename, 'line': line})
    envs = {item['variable']: item for item in result['configuration']}
    a, b = envs.get('MONGODB_DATABASE'), envs.get('MONGODB_DB')
    if a and b and a['default'] != b['default']:
        result['configuration_warnings'].append({'type': 'database_default_mismatch', 'classification': 'potential', 'values': {'MONGODB_DATABASE': a['default'], 'MONGODB_DB': b['default']}, 'migration_action': 'review'})
    seeded = {x['name'] for x in result['collections'] if x['interface'] == 'pymongo'}
    queried = {x['name'] for x in result['collections'] if x['interface'] == 'mongodb_mcp'}
    if seeded and queried and not (seeded & queried):
        result['configuration_warnings'].append({'type': 'collection_name_mismatch', 'classification': 'potential', 'seeded_collections': sorted(seeded), 'mcp_read_collections': sorted(queried), 'migration_action': 'review'})
    return result

