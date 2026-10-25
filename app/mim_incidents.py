"""Read Salesforce incidents through the existing local CLI login, then advise.

No records, tokens, approval decisions or command outputs are persisted.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from urllib.parse import urlsplit

from .mim_dip_recommendation import recommend_from_catalog
from .mim_network_context import NetworkContext, read_context, evaluate_context
from .salesforce_browser import authorize_release, ORG_ALIAS

router = APIRouter()
IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,79}$')


class IncidentMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    object: str
    service: str
    short_description: str
    description: str | None = None
    customer_impact: str | None = None
    node_key: str | None = None

    def columns(self):
        values = self.model_dump(exclude_none=True)
        if any(not IDENTIFIER.fullmatch(value) for value in values.values()):
            raise ValueError('Use Salesforce API identifiers, without expressions or relationships')
        if not self.object.endswith('__c'):
            raise ValueError('Choose the deployed custom incident object')
        return sorted(set(values.values()) - {self.object})


class IncidentSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    record_id: str = Field(pattern=r'^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$')


def configuration():
    filename = os.environ.get('LIFEAFTERCODE_MIM_CONFIG')
    if not filename:
        raise HTTPException(409, 'Set LIFEAFTERCODE_MIM_CONFIG to your private incident mapping and DIP catalog JSON file. See docs/MIM_INCIDENTS.md.')
    try:
        content = Path(filename).read_bytes()
        if len(content) > 2_000_000:
            raise ValueError('Configuration is too large')
        config = json.loads(content)
        mapping = IncidentMapping.model_validate(config['incident'])
        mapping.columns()
        if 'network_context' in config:
            settings = NetworkContext.model_validate(config['network_context'])
            if not mapping.node_key:
                raise ValueError('Network context requires an incident node_key field mapping')
            return mapping, {'network_context': settings}
        catalog = config['catalog']
        if not isinstance(catalog['source_evidence'], list) or not catalog['source_evidence']:
            raise ValueError('Catalog source evidence is required')
        dips = catalog['dips']
        if not isinstance(dips, list) or not 1 <= len(dips) <= 1000:
            raise ValueError('Supply 1 to 1000 reviewed DIPs')
        seen = set()
        for dip in dips:
            if dip.get('review_status') != 'approved':
                raise ValueError('Only explicitly approved catalog entries may be used')
            for key in ('dip_id', 'title', 'service', 'category'):
                if not isinstance(dip.get(key), str) or not dip[key].strip():
                    raise ValueError('Catalog entries require ID, title, service and category')
            if dip['dip_id'] in seen:
                raise ValueError('Duplicate DIP ID')
            seen.add(dip['dip_id'])
            for key in ('implementation_steps', 'validation_steps', 'approval_groups'):
                if not isinstance(dip.get(key), list) or not all(isinstance(v, str) for v in dip[key]):
                    raise ValueError('Catalog steps and approval groups must be string lists')
        return mapping, catalog
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, 'Invalid private MIM configuration; check mapping identifiers and approved catalog entries') from exc


def query_records(mapping, record_id=None):
    # Identifiers are server-owned and validated; the only filter is a validated ID.
    columns = mapping.columns()
    query = f"SELECT Id, LastModifiedDate, {', '.join(columns)} FROM {mapping.object}"
    if record_id:
        if not re.fullmatch(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?', record_id):
            raise HTTPException(400, 'Invalid Salesforce record ID')
        query += f" WHERE Id = '{record_id}'"
    query += ' ORDER BY LastModifiedDate DESC LIMIT 50'
    records = query_salesforce(query)
    return [{key: row.get(key) for key in ['Id', 'LastModifiedDate', *columns]} for row in records]


def query_salesforce(query):
    import shutil
    executable = shutil.which('sf.cmd') or shutil.which('sf')
    if not executable:
        raise HTTPException(503, 'Salesforce CLI is unavailable')
    try:
        result = subprocess.run([executable, 'data', 'query', '--target-org', ORG_ALIAS,
                                 '--query', query, '--json'], capture_output=True, text=True,
                                timeout=60, check=False)
        if result.returncode:
            raise ValueError('Query failed')
        envelope = json.loads(result.stdout)
        records = envelope['result']['records']
        if envelope.get('status') != 0 or envelope['result'].get('done') is False or not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            raise ValueError('Incomplete Salesforce query')
        return records
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(502, 'Salesforce read failed or is incomplete. Check object/field permissions and hackfest-developer login.') from exc


@router.get('/mim', response_class=HTMLResponse)
def workspace():
    return Path(__file__).with_name('mim.html').read_text(encoding='utf-8')


@router.post('/api/mim/incidents')
def incidents(request: Request):
    authorize_release(request)
    mapping, _ = configuration()
    rows = query_records(mapping)
    return {'org_alias': ORG_ALIAS, 'object': mapping.object,
            'records': [{'id': row['Id'], 'title': row.get(mapping.short_description),
                         'service': row.get(mapping.service), 'modified': row['LastModifiedDate']}
                        for row in rows], 'limit': 50, 'execution_enabled': False}


def advise(mapping, catalog, row, source='local_cli_read'):
    payload = {}
    for role, field in mapping.model_dump(exclude_none=True).items():
        if role != 'object':
            value = row.get(field)
            if value is not None and not isinstance(value, str):
                raise HTTPException(409, 'Incident decision fields must contain text')
            payload[role] = value or ''
    result = recommend_from_catalog(catalog, payload)
    selected = next((dip for dip in catalog['dips'] if dip['dip_id'] == result['recommended_dip_id']), None)
    evidence = {'org_alias': ORG_ALIAS if source == 'local_cli_read' else None,
                'source': source, 'object': mapping.object, 'record_id': row['Id'],
                'last_modified': row.get('LastModifiedDate'), 'mapping': mapping.model_dump(exclude_none=True),
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'record_digest': hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest(),
                'catalog_source_evidence': catalog['source_evidence'],
                'authorization_evidence_trusted': False}
    return {'recommendation': result, 'incident': payload, 'evidence': evidence,
            'plan': selected, 'approval_status': 'requires_human_review',
            'write_back_enabled': False, 'execution_enabled': False}


@router.post('/api/mim/recommend')
def recommend(selection: IncidentSelection, request: Request):
    authorize_release(request)
    mapping, catalog = configuration()
    rows = query_records(mapping, selection.record_id)
    if len(rows) != 1:
        raise HTTPException(404, 'Incident not found or not readable')
    row = rows[0]
    if 'network_context' in catalog:
        settings = catalog['network_context']
        node_key = row.get(mapping.node_key)
        evidence_rows, catalog_rows = read_context(settings, node_key, query_salesforce)
        context = evaluate_context(settings, node_key, row.get(mapping.service), evidence_rows, catalog_rows)
        response = advise(mapping, {'dips': [], 'source_evidence': ['Salesforce approved synthetic catalog and imported observations']}, row)
        response.update(context)
        return response
    return advise(mapping, catalog, row)


def allowed_parent_origins():
    values = os.environ.get('LIFEAFTERCODE_SF_PARENT_ORIGINS', '').split(',')
    result = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path or url.query or url.fragment or '*' in value):
            raise HTTPException(409, 'Configure exact HTTPS Salesforce parent origins without paths')
        result.append(value)
    return result


class HostedIncident(BaseModel):
    model_config = ConfigDict(extra='forbid')
    object: str = Field(max_length=80)
    record: dict[str, str | int | float | bool | None] = Field(max_length=100)


@router.get('/api/mim/bridge')
def bridge_configuration():
    return {'parent_origins': allowed_parent_origins()}


@router.post('/api/mim/advise-snapshot')
def advise_snapshot(snapshot: HostedIncident, request: Request):
    # This endpoint evaluates an untrusted snapshot, never performs Salesforce reads.
    # Company runtime authentication remains the reverse proxy's responsibility.
    if (not allowed_parent_origins() or request.headers.get('origin') != str(request.base_url).rstrip('/')
            or request.headers.get('x-lifeaftercode-release') != '1'):
        raise HTTPException(403, 'Hosted snapshot review requires the configured company frontend')
    if sum(len(str(value or '')) for value in snapshot.record.values()) > 100_000:
        raise HTTPException(413, 'Incident snapshot too large')
    mapping, catalog = configuration()
    if 'network_context' in catalog:
        raise HTTPException(409, 'Salesforce network context currently requires the local /mim reader; hosted snapshot transport has no related-evidence reader yet')
    if snapshot.object != mapping.object:
        raise HTTPException(409, 'Selected object does not match the configured incident mapping')
    record_id = snapshot.record.get('Id') or ''
    if not re.fullmatch(r'[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?', record_id):
        raise HTTPException(400, 'Invalid record ID')
    required = {mapping.service, mapping.short_description}
    if not required.issubset(snapshot.record):
        raise HTTPException(409, 'Deploy and approve the configured incident decision fields first')
    row = {key: snapshot.record.get(key) for key in ['Id', 'LastModifiedDate', *mapping.columns()]}
    return advise(mapping, catalog, row, source='salesforce_browser_snapshot')
