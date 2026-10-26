"""Alex procedure lookup over the builder's approved Salesforce mapping.

This is a live catalog lookup, not a node investigation or execution agent.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .published_workspace import published
from .salesforce_browser import authorize_release, ORG_ALIAS
from .mim_incidents import query_salesforce

router = APIRouter()
STOP_WORDS = set('investigate incident show find procedures procedure for on the please failure fault a an me list search'.split())


class AlexQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=500)
    incident_record_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")


@router.get('/alex', response_class=HTMLResponse)
@router.get('/alexa', response_class=HTMLResponse)
def alex_page():
    return Path(__file__).with_name('alex.html').read_text(encoding='utf-8')


@router.post('/api/projects/{project_id}/alex/ask')
def ask(project_id: str, payload: AlexQuestion, request: Request):
    authorize_release(request)
    config = published(project_id)
    fields = config['fields']
    obj, identity = config['object'], config['identity']
    allowed_ids = set(config['allowed_ids'])
    incident_evidence = None
    question = payload.question
    if payload.incident_record_id:
        incident = config.get('incident')
        if not incident:
            raise HTTPException(409, 'The builder has not published an Incident mapping for this workspace')
        rows = query_salesforce(f"SELECT Id, LastModifiedDate, {', '.join(sorted(incident['fields']))} FROM {incident['object']} WHERE Id = '{payload.incident_record_id}' LIMIT 1")
        if len(rows) != 1:
            raise HTTPException(404, 'Selected incident was not found or is not readable')
        row = rows[0]
        values = {source: row.get(target) for target, source in incident['fields'].items()}
        symptoms = ' '.join(str(value) for role, value in values.items()
                            if role in {'service','short_description','description','customer_impact'} and value)
        if not symptoms:
            raise HTTPException(409, 'Publish and populate incident service/summary fields before incident-based lookup')
        question = symptoms
        incident_evidence = {'object': incident['object'], 'record_id': row['Id'],
                             'last_modified': row.get('LastModifiedDate'), 'values': values}
    terms = set(re.findall(r'[a-z0-9]+', question.casefold())) - STOP_WORDS
    base = {'source': 'salesforce', 'publication_digest': config['publication_digest'],
            'incident': incident_evidence, 'org_alias': ORG_ALIAS, 'object': obj,
            'fields': list(fields), 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'method': 'approved_salesforce_catalog_lookup_v1',
            'execution_enabled': False, 'write_back_enabled': False,
            'authorization_evidence_trusted': False}
    if re.search(r'\bnode[\s-]*\d+\b', payload.question, re.I):
        return {**base, 'status': 'clarification_required', 'records': [],
                'reply': 'This workspace searches Salesforce procedures. It has no node diagnostics attached; ask for a procedure topic such as BFD.'}
    if not terms:
        return {**base, 'status': 'clarification_required', 'records': [],
                'reply': 'Which procedure topic or ID should I look up in Salesforce?'}
    # Only server-derived reviewed identifiers enter SOQL. User text is matched locally.
    rows = query_salesforce(f"SELECT Id, Name, LastModifiedDate, {', '.join(sorted(fields))} FROM {obj} LIMIT 1001")
    if len(rows) > 1000:
        raise HTTPException(409, 'Catalog exceeds the bounded lookup window; narrow the server-side scope before continuing')
    matches = []
    for row in rows:
        if row.get(identity) not in allowed_ids:
            continue
        values = {source: row.get(target) for target, source in fields.items()}
        text = ' '.join(str(value) for value in values.values() if value is not None).casefold()
        words = set(re.findall(r'[a-z0-9]+', text))
        matched = sorted(terms & words)
        if matched:
            matches.append({'record_id': row['Id'], 'procedure_id': row[identity],
                            'last_modified': row.get('LastModifiedDate'), 'values': values,
                            'matched_terms': matched, 'score': len(matched)})
    matches.sort(key=lambda item: (-item['score'], item['procedure_id']))
    return {**base, 'status': 'matches' if matches else 'no_match',
            'match_count': len(matches), 'records': matches[:20],
            'reply': (f'Found {len(matches)} matching Salesforce procedure records. Review the source records and steps; no diagnosis, approval or recovery was performed.'
                      if matches else 'No matching synced Salesforce procedures were found. Check that the relevant IDs, titles and steps were approved and synced. No simulation fallback was used.')}


@router.post('/api/alexa/ask')
def ask_active(payload: AlexQuestion, request: Request):
    authorize_release(request)
    return ask(published()['project_id'], payload, request)


@router.post('/api/alexa/config')
def active_configuration(request: Request):
    authorize_release(request)
    config = published()
    return {key: config[key] for key in ('project_id','org_alias','object','published_at','publication_digest')}


@router.post('/api/projects/{project_id}/alexa/incidents')
def incidents(project_id: str, request: Request):
    authorize_release(request)
    config = published(project_id)
    incident = config.get('incident')
    if not incident:
        return {'records': [], 'message': 'No Incident mapping published yet. Procedure topic lookup is available.'}
    fields = incident['fields']
    rows = query_salesforce(f"SELECT Id, LastModifiedDate, {', '.join(sorted(fields))} FROM {incident['object']} ORDER BY LastModifiedDate DESC LIMIT 50")
    return {'records': [{'id': row['Id'], 'label': next((str(row.get(target)) for target, source in fields.items()
                                  if source in {'short_description','incident_id'} and row.get(target)), row['Id'])} for row in rows],
            'message': 'Choose an incident to retrieve matching procedures using its Salesforce content.'}


@router.post('/api/projects/{project_id}/alexa/config')
def project_configuration(project_id: str, request: Request):
    authorize_release(request)
    config = published(project_id)
    return {key: config[key] for key in ('project_id','org_alias','object','published_at','publication_digest')}
