"""Build a record upsert from server-saved source data and approved schema fields."""
import json

from .canonical_project_api import load_saved_review, project_paths, load_ir
from .procedure_catalog import IDENTITIES
from .salesforce import api_name, object_api_name
from .seeded_network_import import digest


def record_plan(project_id):
    review = load_saved_review(project_id)
    _, snapshot, _ = project_paths(project_id)
    ir = load_ir(snapshot)
    entity = next((e for e in review.entities if e.concept == 'DIP' and e.status == 'approved'), None)
    if not entity:
        raise ValueError('Approve the Procedure entity and its fields before syncing records')
    fields = [f for f in entity.fields if f.status == 'approved']
    identities = [f for f in fields if f.external_id]
    if len(identities) != 1:
        raise ValueError('Approve exactly one procedure identity field as a unique external ID, then validate and redeploy')
    identity = identities[0]
    if identity.source.rsplit('.', 1)[-1] not in IDENTITIES:
        raise ValueError('Record sync requires a source procedure ID')
    def target(field):
        return api_name(field.target.removesuffix('__c')) + '__c'
    names = [target(field).casefold() for field in fields]
    if len(names) != len(set(names)):
        raise ValueError('Approved fields have colliding Salesforce targets')
    rows, seen = [], set()
    for catalog in ir.procedure_catalogs:
        if catalog['name'] not in entity.source_representations:
            continue
        for item in catalog['records']:
            identity_name = identity.source.rsplit('.', 1)[-1]
            key = item['record'].get(identity_name, item['procedure_id'])
            if not isinstance(key, str) or not key.strip():
                raise ValueError('Procedure identity must be nonempty text')
            if key.casefold() in seen:
                raise ValueError('Procedure IDs overlap across catalogs; resolve identity collisions before syncing')
            seen.add(key.casefold())
            row = {'Name': key[:80]}
            for field in fields:
                source = field.source.rsplit('.', 1)[-1]
                if field is identity:
                    value = key
                elif source not in item['record']:
                    continue  # A missing property is not authorization to clear an existing field.
                else:
                    value = item['record'][source]
                if value is None:
                    continue
                if isinstance(value, (list, dict)):
                    if field.data_type != 'LongTextArea':
                        raise ValueError('Structured procedure data requires approved LongTextArea fields')
                    value = json.dumps(value, sort_keys=True, separators=(',', ':'))
                elif isinstance(value, bool):
                    value = 'true' if value else 'false'
                else:
                    value = str(value)
                if field.data_type in {'Text', 'LongTextArea'}:
                    limit = 255 if field.data_type == 'Text' else 131072
                    if len(value.encode('utf-16-le')) // 2 > limit:
                        raise ValueError('Procedure value exceeds the approved Salesforce field length')
                row[target(field)] = value
            rows.append(row)
    if not rows:
        raise ValueError('No procedure records match the approved source representations; rescan the repository')
    # Identical CSV columns avoid clearing absent properties during bulk upsert.
    groups = {}
    for row in rows:
        groups.setdefault(tuple(sorted(row)), []).append(row)
    result = {'org_alias': 'hackfest-developer', 'batches': [
        {'object': object_api_name(review.repository_id, entity.concept),
         'external_id': target(identity), 'rows': items} for items in groups.values()],
        'repository_id': review.repository_id, 'execution_enabled': False}
    result['review_digest'] = digest(result)
    return result


def summary(plan):
    return {'record_digest': plan['review_digest'],
            'record_count': sum(len(batch['rows']) for batch in plan['batches']),
            'object': plan['batches'][0]['object'], 'external_id': plan['batches'][0]['external_id'],
            'fields': sorted({key for b in plan['batches'] for row in b['rows'] for key in row}),
            'execution_enabled': False}
