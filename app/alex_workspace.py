"""Alex procedure lookup over the builder's approved Salesforce mapping.

This is a live catalog lookup, not a node investigation or execution agent.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .canonical_project_api import load_saved_review
from .procedure_sync import record_plan
from .salesforce import api_name
from .salesforce_browser import authorize_release, ORG_ALIAS
from .mim_incidents import query_salesforce

router = APIRouter()
STOP_WORDS = set('investigate incident show find procedures procedure for on the please failure fault a an me list search'.split())


class AlexQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=500)


@router.get('/alex', response_class=HTMLResponse)
@router.get('/alexa', response_class=HTMLResponse)
def alex_page():
    return Path(__file__).with_name('alex.html').read_text(encoding='utf-8')


@router.post('/api/projects/{project_id}/alex/ask')
def ask(project_id: str, payload: AlexQuestion, request: Request):
    authorize_release(request)
    try:
        plan = record_plan(project_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    review = load_saved_review(project_id)
    entity = next(e for e in review.entities if e.concept == 'DIP' and e.status == 'approved')
    fields = {api_name(f.target.removesuffix('__c')) + '__c': f.source.rsplit('.', 1)[-1]
              for f in entity.fields if f.status == 'approved'}
    obj = plan['batches'][0]['object']
    identity = plan['batches'][0]['external_id']
    allowed_ids = {row[identity] for batch in plan['batches'] for row in batch['rows']}
    terms = set(re.findall(r'[a-z0-9]+', payload.question.casefold())) - STOP_WORDS
    base = {'source': 'salesforce', 'org_alias': ORG_ALIAS, 'object': obj,
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
