"""Static seed discovery and explicit Salesforce upsert planning; no seed execution."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = 'http://soap.sforce.com/2006/04/metadata'
ET.register_namespace('', NS)
IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,79}__c$')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def discover(root, namespace):
    """Read known JSON seeds and exported runtime evidence, never execute Python/HCL.

    Namespace identifies a lab, not a file/archive hash, so repeated exports upsert.
    """
    if not namespace or len(namespace) > 120:
        raise ValueError('Supply a stable lab namespace of 1–120 characters')
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Source directory does not exist')
    found = {}
    warnings = []

    def add(kind, identity, payload, file, node=None, observed=None):
        key = digest({'namespace': namespace, 'kind': kind, 'identity': identity})
        record = {'kind': kind, 'key': key, 'namespace': namespace,
                  'source_file': str(file.relative_to(root)), 'source_digest': digest(payload),
                  'provenance': 'synthetic', 'payload': payload,
                  'node_id': node, 'observed_at': observed, 'review_status': 'needs_review'}
        prior = found.get(key)
        if prior and prior['source_digest'] != record['source_digest']:
            raise ValueError('Conflicting source records share a stable identity')
        found.setdefault(key, record)

    def node(row, file):
        if not isinstance(row, dict) or not isinstance(row.get('device_id'), str):
            raise ValueError('Network export rows require device_id')
        if row.get('simulation_only') is not True:
            raise ValueError('Only explicitly simulation_only network exports are accepted')
        device_id = row['device_id']
        inventory = {key: row[key] for key in ('device_id', 'management_ip', 'site', 'role', 'peer_id') if key in row}
        add('node', device_id, inventory, file, node=device_id)
        if 'sample' in row:
            if not isinstance(row.get('observed_at'), str) or not isinstance(row.get('sample'), dict):
                raise ValueError('Observations require timestamp and sample')
            # Content changes at the same timestamp are distinct immutable observations.
            add('observation', [device_id, row['observed_at'], digest(row)], row, file,
                node=device_id, observed=row['observed_at'])

    files = sorted(root.rglob('*.json'))
    if len(files) > 20000:
        raise ValueError('Too many JSON files')
    total = 0
    for file in files:
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            continue
        if file.name not in {'synthetic_network_mops.json', 'mops.json', 'network_command_fixtures.json', 'network-export.json'}:
            continue
        size = file.stat().st_size
        total += size
        if size > 30_000_000 or total > 50_000_000:
            raise ValueError('Seed input exceeds size limit')
        value = json.loads(file.read_text(encoding='utf-8'))
        if file.name in {'synthetic_network_mops.json', 'mops.json'}:
            if not isinstance(value, list):
                raise ValueError('Expected a procedure list')
            for dip in value:
                if not isinstance(dip, dict) or not isinstance(dip.get('provenance'), dict):
                    raise ValueError('Invalid procedure record')
                if (dip.get('provenance', {}).get('kind') != 'synthetic'
                        or dip.get('execution_enabled') is not False):
                    raise ValueError('Expected synthetic, execution-disabled procedures')
                if not all(isinstance(dip.get(key), str) and dip[key] for key in ('dip_id', 'title', 'service')):
                    raise ValueError('Procedure identity, title and service required')
                add('dip', [dip['dip_id'], dip.get('contract_version', '1')], dip, file)
        elif file.name == 'network_command_fixtures.json':
            if not isinstance(value, dict) or not isinstance(value.get('commands'), dict) or not isinstance(value.get('profile'), str):
                raise ValueError('Invalid command fixture profile')
            for command_key, command in value['commands'].items():
                if not isinstance(command, dict) or not isinstance(command.get('outputs'), dict) or not all(isinstance(command.get(k), str) for k in ('command', 'platform')):
                    raise ValueError('Invalid command fixture')
                for variant, output in command['outputs'].items():
                    if not isinstance(output, str):
                        raise ValueError('Command fixture output must be text')
                    add('command_fixture', [value['profile'], command_key, variant],
                        {'profile': value['profile'], 'command_key': command_key,
                         'command': command['command'], 'platform': command['platform'],
                         'variant': variant, 'output': output, 'template_only': True}, file)
        else:
            if not isinstance(value, dict) or value.get('simulation_only') is not True or not isinstance(value.get('nodes'), list):
                raise ValueError('network-export.json requires simulation_only=true and nodes list')
            for row in value['nodes']:
                node(row, file)
    if not any(row['kind'] == 'node' for row in found.values()):
        warnings.append('No exported node inventory found. Python/Terraform generators are not executed. Export runtime snapshots to network-export.json to include nodes and observations.')
    return {'namespace': namespace, 'records': sorted(found.values(), key=lambda row: (row['kind'], row['key'])),
            'warnings': warnings, 'execution_enabled': False}


DEFAULT_MAPPING = {
    'dip': {'object': 'MIM_DIP__c', 'key': 'CatalogKey__c',
            'fields': {'SourceDIPId__c': 'dip_id', 'Title__c': 'title', 'Service__c': 'service',
                       'Category__c': 'category', 'ContractVersion__c': 'contract_version',
                       'ContractJSON__c': '$payload', 'ContractDigest__c': '$source_digest',
                       'ProvenanceKind__c': '$provenance',
                       'CatalogReviewStatus__c': '$review_status'}},
    'evidence': {'object': 'MIM_NetworkEvidence__c', 'key': 'SourceKey__c',
                 'fields': {'EvidenceKind__c': '$kind', 'LabNamespace__c': '$namespace',
                            'SourceFile__c': '$source_file', 'SourceDigest__c': '$source_digest',
                            'NodeKey__c': '$node_key', 'ObservedAt__c': '$observed_at',
                            'EvidenceJSON__c': '$payload', 'ProvenanceKind__c': '$provenance'}},
}


def plan(discovery, mapping=None):
    mapping = mapping or DEFAULT_MAPPING
    batches = {}
    for source in discovery['records']:
        target = mapping['dip' if source['kind'] == 'dip' else 'evidence']
        obj, key = target['object'], target['key']
        for identifier in [obj, key, *target['fields']]:
            if not IDENTIFIER.fullmatch(identifier):
                raise ValueError('Invalid custom object/field API name')
        if key in target['fields']:
            raise ValueError('External key cannot be overwritten by a field mapping')
        # Reuse the existing Salesforce catalog identity exactly; no duplicate DIP copies.
        identity = digest({'dip_id': source['payload']['dip_id'],
                           'version': source['payload'].get('contract_version', '1')}) if source['kind'] == 'dip' else source['key']
        row = {key: identity}
        for field, expression in target['fields'].items():
            if expression == '$payload':
                value = json.dumps(source['payload'], sort_keys=True, separators=(',', ':'))
            elif expression == '$node_key':
                value = digest({'namespace': discovery['namespace'], 'kind': 'node', 'identity': source['node_id']}) if source['node_id'] else ''
            elif expression.startswith('$'):
                name = expression[1:]
                if name not in source:
                    raise ValueError('Unsupported source field mapping')
                value = source[name] or ''
            else:
                value = source['payload'].get(expression, '')
            if isinstance(value, (dict, list)):
                raise ValueError('Use $payload for structured values')
            row[field] = str(value)
        batch = batches.setdefault(obj, {'object': obj, 'external_id': key, 'rows': []})
        if batch['external_id'] != key:
            raise ValueError('An object cannot use multiple external IDs in one import')
        batch['rows'].append(row)
    for batch in batches.values():
        keys = [row[batch['external_id']] for row in batch['rows']]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate target identity; review source catalog/lab mapping')
    result = {'org_alias': 'hackfest-developer', 'namespace': discovery['namespace'],
              'batches': list(batches.values()), 'warnings': discovery['warnings'],
              'baseline_update_enabled': False, 'execution_enabled': False}
    result['review_digest'] = digest(result)
    return result


def schema_review(batch, describe):
    """No fuzzy field matching or destructive type changes; list missing fields."""
    fields = {field['name']: field for field in describe['fields']}
    problems, missing = [], []
    if not describe.get('createable') or not describe.get('updateable'):
        problems.append('Object requires create and update access')
    for name in sorted({name for row in batch['rows'] for name in row}):
        field = fields.get(name)
        length = max(len(row.get(name, '').encode('utf-16-le')) // 2 for row in batch['rows'])
        long_text = length > 255 or name.endswith('JSON__c')
        if length > 131072:
            problems.append(f'{name}: value exceeds Salesforce text limit')
        if not field:
            missing.append({'name': name, 'type': 'LongTextArea' if long_text else 'Text',
                            'length': 131072 if long_text else 255,
                            'external_id': name == batch['external_id']})
            continue
        if (field.get('type') not in {'string', 'textarea'} or not field.get('createable')
                or not field.get('updateable') or field.get('length', 0) < length):
            problems.append(f'{name}: incompatible type, length or write permissions')
        if name == batch['external_id'] and (not field.get('externalId') or not field.get('unique')):
            problems.append(f'{name}: must be a unique external ID; do not import until reviewed')
    supplied = {key for row in batch['rows'] for key in row}
    for field in fields.values():
        if (field.get('createable') and not field.get('nillable', True)
                and not field.get('defaultedOnCreate') and not field.get('autoNumber')
                and field['name'] not in supplied):
            problems.append(field['name'] + ': required unmapped field blocks inserts')
    return {'object': batch['object'], 'missing_fields': missing, 'blockers': problems}


def write_field_proposals(review, destination):
    """Export missing field metadata only. No existing schema is rewritten."""
    destination = Path(destination)
    for field in review['missing_fields']:
        if field['length'] > 131072:
            raise ValueError('Value exceeds Salesforce long text field limit')
        root = ET.Element('{' + NS + '}CustomField')
        values = {'fullName': field['name'], 'label': field['name'].removesuffix('__c').replace('_', ' '),
                  'type': field['type'], 'length': field['length']}
        if field['type'] == 'LongTextArea':
            values['visibleLines'] = 4
        if field['external_id']:
            values.update(externalId='true', unique='true')
        for key, value in values.items():
            ET.SubElement(root, '{' + NS + '}' + key).text = str(value)
        path = destination / 'objects' / review['object'] / 'fields' / (field['name'] + '.field-meta.xml')
        path.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def discover_entries(entries, namespace):
    """Adapt the bounded repository reader without executing or extracting a ZIP."""
    import tempfile
    from pathlib import PurePosixPath
    names = {'synthetic_network_mops.json', 'mops.json', 'network_command_fixtures.json', 'network-export.json'}
    with tempfile.TemporaryDirectory() as folder:
        for name, content in entries:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or path.name not in names:
                continue
            target = Path(folder).joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        return discover(folder, namespace)
