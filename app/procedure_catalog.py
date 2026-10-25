"""One source-backed procedure concept for DIP, MOP, SOP and runbook catalogs.

Procedure definitions describe proposed steps; they do not authorize execution.
"""
import hashlib
import json
from pathlib import PurePosixPath
import re

FILENAMES = {'dips.json': 'DIP', 'mops.json': 'MOP', 'sops.json': 'SOP',
             'synthetic_network_mops.json': 'MOP', 'runbooks.json': 'Runbook',
             'procedures.json': 'Procedure'}
IDENTITIES = ('procedure_id', 'dip_id', 'mop_id', 'sop_id', 'runbook_id', 'id')
STEP_FIELDS = ('implementation_steps', 'steps', 'actions', 'validation_steps', 'rollback_steps')
# DIP remains the stored concept/API suffix to preserve existing metadata identity.
PROCEDURE_CONCEPT = 'DIP'


def is_procedure_name(name):
    words = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    words = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', words)
    return bool(re.search(r'\b(dips?|mops?|sops?|procedures?|runbooks?)\b', words.replace('_', ' '), re.I))


def pointer_token(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def read_procedure_catalogs(entries):
    catalogs, warnings = [], []
    for filename, content in entries:
        subtype = FILENAMES.get(PurePosixPath(filename).name.lower())
        if not subtype:
            continue
        try:
            raw = json.loads(content)
        except ValueError:
            warnings.append(f'{filename}: invalid procedure JSON; no schema inferred')
            continue
        prefix = ''
        if isinstance(raw, dict):
            for key in ('procedures', 'dips', 'mops', 'sops', 'runbooks'):
                if isinstance(raw.get(key), list):
                    raw, prefix = raw[key], '/' + key
                    break
        rows = raw if isinstance(raw, list) else [raw]
        records = []
        for index, row in enumerate(rows):
            identity = next((key for key in IDENTITIES if isinstance(row, dict) and isinstance(row.get(key), str) and row[key].strip()), None)
            if not identity or not any(isinstance(row.get(key), list) for key in STEP_FIELDS):
                warnings.append(f'{filename}: record {index} lacks an ID or structured procedure steps; skipped')
                continue
            reference = prefix + '/' + str(index) if isinstance(raw, list) else ''
            records.append({'procedure_type': subtype, 'procedure_id': row[identity],
                            'title': row.get('title') or row[identity], 'service': row.get('service'),
                            'source_file': filename, 'reference': reference,
                            'record': row})
        if records:
            # A catalog schema is inferred from actual keys, not invented fields.
            fields = []
            for key in sorted({key for item in records for key in item['record']}):
                values = [item['record'][key] for item in records if key in item['record'] and item['record'][key] is not None]
                first = next(item for item in records if key in item['record'])
                if any(isinstance(value, (dict, list)) or (isinstance(value, str) and len(value) > 255) for value in values):
                    typ = 'LongTextArea'
                elif values and all(isinstance(value, bool) for value in values):
                    typ = 'Checkbox'
                elif values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
                    typ = 'Number'
                else:
                    typ = 'Text'
                fields.append({'key': key, 'type': typ,
                               'reference': first['reference'] + '/' + pointer_token(key)})
            name = subtype.upper() + 'Catalog_' + hashlib.sha256(filename.encode()).hexdigest()[:10] + '_Procedure'
            catalogs.append({'name': name, 'procedure_type': subtype, 'source_file': filename,
                             'records': records, 'fields': fields})
    return catalogs, warnings
