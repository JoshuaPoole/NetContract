"""Read-only, evidence-backed SQLAlchemy/Drizzle table relationship analysis.

This module reports declared schema differences, not live database drift.
"""
import ast
import re
from pathlib import PurePosixPath

TABLE_PATTERN = re.compile(r'\b(?:export\s+)?const\s+(\w+)\s*=\s*mysqlTable\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')
FIELD_PATTERN = re.compile(r'^\s*(\w+)\s*:\s*\w+\s*\(\s*[\'\"]([^\'\"]+)[\'\"]', re.M)


def _line(source, offset):
    return source.count('\n', 0, offset) + 1


def _braced_block(source, start):
    """Find first object literal after mysqlTable name; account for strings/comments."""
    pos = source.find('{', start)
    if pos < 0:
        return '', start
    depth = 0
    quote = None
    comment = None
    i = pos
    while i < len(source):
        ch = source[i]
        nxt = source[i:i+2]
        if comment == 'line':
            if ch == '\n': comment = None
        elif comment == 'block':
            if nxt == '*/': comment = None; i += 1
        elif quote:
            if ch == '\\': i += 1
            elif ch == quote: quote = None
        elif nxt == '//': comment = 'line'; i += 1
        elif nxt == '/*': comment = 'block'; i += 1
        elif ch in "'\"`": quote = ch
        elif ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0: return source[pos+1:i], pos+1
        i += 1
    return '', pos


def _python_tables(filename, source):
    try: tree = ast.parse(source)
    except SyntaxError: return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef): continue
        table = None
        columns = set()
        for stmt in node.body:
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)): continue
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            for target in targets:
                if not isinstance(target, ast.Name): continue
                if target.id == '__tablename__' and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    table = value.value
                if isinstance(value, ast.Call) and isinstance(value.func, (ast.Name, ast.Attribute)) and ast.unparse(value.func).split('.')[-1] in ('Column', 'mapped_column'):
                    physical = target.id
                    if value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str):
                        physical = value.args[0].value
                    columns.add(physical)
        if table:
            found.append({'table':table,'model':node.name,'source_file':filename,'line':node.lineno,'columns':sorted(columns)})
    return found


def _drizzle_tables(filename, source):
    found = []
    for match in TABLE_PATTERN.finditer(source):
        block, block_start = _braced_block(source, match.end())
        if not block: continue
        columns = sorted({m.group(2) for m in FIELD_PATTERN.finditer(block)})
        found.append({'table':match.group(2),'model':match.group(1),'source_file':filename,'line':_line(source, match.start()),'columns':columns})
    return found


def analyze_schema_relationships(entries):
    """Accept (filename, decoded_text) entries from the existing safe ZIP reader."""
    python, drizzle, evidence = {}, {}, []
    for filename, source in entries:
        normalized = filename.replace('\\', '/')
        if normalized.endswith('.py') and '/models/' in '/' + normalized:
            for item in _python_tables(filename, source): python.setdefault(item['table'], []).append(item)
        if normalized.endswith('/drizzle/schema.ts'):
            for item in _drizzle_tables(filename, source): drizzle.setdefault(item['table'], []).append(item)
            lines = source.splitlines()
            for i, line in enumerate(lines):
                # Restrict ownership rules to explicit repository comments, not inference.
                if 'Owned/created by the web business' in line and 'Python/SQLAlchemy' in line:
                    evidence.append({'table':'owner_config','rule':'python_owned_drizzle_read_mapping','source_file':filename,'line':i+1,'excerpt':' '.join(x.strip() for x in lines[i:i+5])[:350]})
                if 'Do NOT run drizzle-kit generate/migrate for this table' in line:
                    evidence.append({'table':'owner_config','rule':'no_drizzle_migrations','source_file':filename,'line':i+1,'excerpt':line.strip()})
                if 'canonical column def' in line and i >= 1 and 'CatalogueItem.tenant_id' in line:
                    evidence.append({'table':'catalogue_items','column':'tenant_id','rule':'python_canonical_column','source_file':filename,'line':i+1,'excerpt':' '.join(x.strip() for x in lines[max(0,i-2):i+1])[:350]})
    shared = []
    for table in sorted(set(python) & set(drizzle)):
        py_cols = set().union(*(set(x['columns']) for x in python[table]))
        ts_cols = set().union(*(set(x['columns']) for x in drizzle[table]))
        rules = [e for e in evidence if e['table'] == table]
        shared.append({'table':table,'python_declarations':python[table], 'drizzle_declarations':drizzle[table],
                       'python_only_columns':sorted(py_cols-ts_cols), 'drizzle_only_columns':sorted(ts_cols-py_cols),
                       'ownership':'python' if any(e['rule']=='python_owned_drizzle_read_mapping' for e in rules) else 'unresolved',
                       'migration_restrictions':['no_drizzle_migrations'] if any(e['rule']=='no_drizzle_migrations' for e in rules) else [],
                       'evidence':rules, 'classification':'declared_schema_difference' if py_cols != ts_cols else 'column_names_match',
                       'migration_action':'none_without_approval'})
    return {'analysis_type':'static_declarations_only','shared_tables':shared,
            'python_only_tables':sorted(set(python)-set(drizzle)),
            'drizzle_only_tables':sorted(set(drizzle)-set(python)),
            'warnings':['Column differences are not proof of physical database drift; types, constraints, defaults and actual usage have not been reconciled.']}

