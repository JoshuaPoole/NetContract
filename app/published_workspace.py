"""Publish a frozen Salesforce mapping only after successful record sync.

Record values are always read from Salesforce; drafts never change this mapping.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from fastapi import HTTPException

from .canonical_project_api import load_saved_review
from .salesforce import api_name, object_api_name
from .seeded_network_import import digest


def root():
    return Path(os.environ.get('MAPPER_WORKSPACE', 'workspace'))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(project_id, records, review=None):
    review = review or load_saved_review(project_id)
    entity = next(e for e in review.entities if e.concept == 'DIP' and e.status == 'approved')
    fields = {api_name(f.target.removesuffix('__c')) + '__c': f.source.rsplit('.', 1)[-1]
              for f in entity.fields if f.status == 'approved'}
    incident = next((e for e in review.entities if e.concept == 'Incident' and e.status == 'approved'
                     and any(f.status == 'approved' for f in e.fields)), None)
    value = {'project_id': project_id, 'org_alias': records['org_alias'],
             'object': records['batches'][0]['object'], 'identity': records['batches'][0]['external_id'],
             'fields': fields,
             'allowed_ids': sorted({row[records['batches'][0]['external_id']]
                                    for batch in records['batches'] for row in batch['rows']}),
             'record_digest': records['review_digest'],
             'published_at': datetime.now(timezone.utc).isoformat(),
             'incident': {'object': object_api_name(review.repository_id, 'Incident'),
                          'fields': {api_name(f.target.removesuffix('__c')) + '__c': f.source.rsplit('.', 1)[-1]
                                     for f in incident.fields if f.status == 'approved'}} if incident else None}
    value['publication_digest'] = digest(value)
    atomic_json(root() / (project_id + '.published.json'), value)
    atomic_json(root() / 'alexa-active.json', {'project_id': project_id})
    return value


def published(project_id=None):
    try:
        if not project_id:
            pointer = root() / 'alexa-active.json'
            if not pointer.exists():
                raise HTTPException(409, 'No published workspace yet. Deploy and sync procedures from the builder, or activate verified existing Salesforce records.')
            project_id = json.loads(pointer.read_text(encoding='utf-8'))['project_id']
        if not isinstance(project_id, str) or not project_id.isalnum():
            raise HTTPException(400, 'Invalid published project ID')
        path = root() / (project_id + '.published.json')
        if not path.exists():
            raise HTTPException(409, 'This project has not been published. Deploy and sync, or activate verified existing Salesforce records from its builder review.')
        value = json.loads(path.read_text(encoding='utf-8'))
        expected = value.pop('publication_digest')
        if value.get('project_id') != project_id or digest(value) != expected:
            raise ValueError('Publication digest mismatch')
        value['publication_digest'] = expected
        return value
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(409, 'Published workspace configuration is unavailable or invalid') from exc
