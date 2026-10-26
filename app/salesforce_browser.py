"""Local browser adapter over the saved canonical review and existing CLI release."""
from copy import deepcopy
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .canonical_project_api import load_saved_review, reviewed_metadata_bundle, project_paths
from .reviewed_metadata import export_reviewed_metadata
from scripts.salesforce_deploy_playbook import (
    generate_lightning_app, generate_permissions, inspect_objects, normalize_frontend_url, SFNS,
)

router = APIRouter()
ORG_ALIAS = 'hackfest-developer'
ROOT = Path(__file__).resolve().parents[1]
STATE_LOCK = Lock()
JOBS = {}
VALIDATIONS = {}


class FrontendSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    frontend_url: str = Field(default='', max_length=2048)


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    org_alias: Literal['hackfest-developer'] = ORG_ALIAS
    review_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    assign_to_current_user: bool = False
    sync_records: bool = False
    record_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def local_request(request):
    try:
        return (request.url.hostname in {'localhost', '127.0.0.1', '::1'}
                and ip_address(request.client.host).is_loopback)
    except (ValueError, AttributeError):
        return False


def capability(request):
    if os.environ.get('LIFEAFTERCODE_BROWSER_DEPLOY') != '1' or not local_request(request):
        return False, 'Start python run.py on this computer at localhost to enable browser deployment.'
    if not (shutil.which('sf.cmd') or shutil.which('sf')):
        return False, 'Install Salesforce CLI and authenticate hackfest-developer on the computer running this app.'
    return True, 'Uses the Salesforce CLI login on this computer for hackfest-developer.'


def authorize_local_page(request):
    if os.environ.get('LIFEAFTERCODE_BROWSER_DEPLOY') != '1' or not local_request(request):
        raise HTTPException(403, 'Configure releases from the local review page started by python run.py')
    origin = urlsplit(request.headers.get('origin', ''))
    if (request.headers.get('x-lifeaftercode-release') != '1'
            or origin.scheme != request.url.scheme or origin.netloc != request.url.netloc):
        raise HTTPException(403, 'Release requests must come from this local review page')


def authorize_release(request):
    authorize_local_page(request)
    enabled, reason = capability(request)
    if not enabled:
        raise HTTPException(403, reason)


def frontend_settings(project_id):
    project, _, _ = project_paths(project_id)
    path = project.with_suffix('.frontend.json')
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'frontend_url': ''}
    return {'frontend_url': normalize_frontend_url(value.get('frontend_url', ''))}


@router.get('/api/projects/{project_id}/salesforce/frontend')
def get_frontend_settings(project_id: str):
    return frontend_settings(project_id)


@router.put('/api/projects/{project_id}/salesforce/frontend')
def save_frontend_settings(project_id: str, payload: FrontendSettings, request: Request):
    authorize_local_page(request)
    project, _, _ = project_paths(project_id)
    try:
        settings = {'frontend_url': normalize_frontend_url(payload.frontend_url)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with STATE_LOCK:
        if any(job['status'] in {'queued', 'running'} for job in JOBS.values()):
            raise HTTPException(409, 'Wait for the running release before changing its frontend URL')
        project.with_suffix('.frontend.json').write_text(json.dumps(settings), encoding='utf-8')
        VALIDATIONS.pop((project_id, ORG_ALIAS), None)
    return settings


def permission_snapshot(project_id):
    """Read the matrix from the very same XML generator used by deployment."""
    plan = load_saved_review(project_id)
    frontend_url = frontend_settings(project_id)['frontend_url']
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        export_reviewed_metadata(plan, root)
        default = root / 'force-app/main/default'
        objects = inspect_objects(default / 'objects')
        permission_name = generate_permissions(objects, default / 'permissionsets')
        application_name = generate_lightning_app(objects, default, permission_name, 'LifeAfterCode', frontend_url)
        xml = ET.parse(default / 'permissionsets' / f'{permission_name}.permissionset-meta.xml').getroot()
        def rows(tag):
            return [{child.tag.removeprefix('{' + SFNS + '}'): child.text for child in row}
                    for row in xml.findall('{' + SFNS + '}' + tag)]
        matrix = {'objects': rows('objectPermissions'), 'fields': rows('fieldPermissions')}
    digest = hashlib.sha256(json.dumps({
        'review': plan.model_dump(), 'permissions': matrix,
        'permission_set': permission_name, 'application': application_name, 'frontend_url': frontend_url,
    }, sort_keys=True).encode()).hexdigest()
    return plan, {'org_alias': ORG_ALIAS, 'review_digest': digest,
                  'permission_set': permission_name, 'application': application_name,
                  'frontend_url': frontend_url,
                  'workspace_tab': permission_name.removesuffix('_Access') + '_Workspace' if frontend_url else None,
                  **matrix}


@router.get('/api/projects/{project_id}/salesforce/permissions')
def permissions(project_id: str, request: Request):
    try:
        _, snapshot = permission_snapshot(project_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    enabled, reason = capability(request)
    return {**snapshot, 'deployment_enabled': enabled, 'message': reason}


def execute_release(bundle, approve, assign, frontend_url=""):
    """The browser invokes the existing runner, never another conversion engine."""
    with tempfile.TemporaryDirectory(prefix='lifeaftercode-browser-', ignore_cleanup_errors=True) as directory:
        archive = Path(directory) / 'reviewed.zip'
        archive.write_bytes(bundle)
        command = [sys.executable, str(ROOT / 'run.py'), 'salesforce',
                   '--metadata-zip', str(archive), '--org', ORG_ALIAS]
        if frontend_url:
            command += ['--frontend-url', normalize_frontend_url(frontend_url)]
        if approve:
            command.append('--approve')
        if assign:
            command.append('--assign-to-current-user')
        result = subprocess.run(command, cwd=ROOT, text=True, encoding='utf-8',
                                errors='replace', capture_output=True, timeout=3600, check=False)
    output = (result.stdout + '\n' + result.stderr).strip()[-16000:]
    if result.returncode:
        raise RuntimeError(output or 'Salesforce CLI did not confirm success')
    return output


def run_job(identifier, bundle):
    with STATE_LOCK:
        job = JOBS[identifier]
        job['status'] = 'running'
    try:
        # A review edited while this job was queued cannot authorize the old job.
        deployment_review, current = permission_snapshot(job['project_id'])
        if current['review_digest'] != job['review_digest']:
            raise RuntimeError('Review changed; save and validate the current mappings')
        arguments = (bundle, job['action'] == 'deploy', job['assign_to_current_user'])
        output = (execute_release(*arguments, frontend_url=job['frontend_url'])
                  if job['frontend_url'] else execute_release(*arguments))
        if job['action'] == 'deploy':
            job['schema_deployed'] = True
            job['log'] = output
        if job.get('sync_records'):
            from .procedure_sync import record_plan
            from scripts.seeded_network_sf import apply
            records = record_plan(job['project_id'])
            _, latest = permission_snapshot(job['project_id'])
            if latest['review_digest'] != job['review_digest'] or records['review_digest'] != job['record_digest']:
                raise RuntimeError('Schema deployed, but review changed before record sync; no record sync started')
            job['schema_deployed'] = True
            job['log'] = output + '\nSchema deployed. Starting reviewed record sync.'
            receipts = apply(records, records['review_digest'], shutil.which('sf.cmd') or shutil.which('sf'))
            from .published_workspace import publish
            publication = publish(job['project_id'], records, review=deployment_review)
            output += '\nProcedure record sync confirmed: ' + json.dumps(receipts)
            output += '\nPublished Alexa workspace: /alexa?project=' + job['project_id'] + ' (' + publication['publication_digest'] + ')'
        with STATE_LOCK:
            job['status'] = 'deployed' if job['action'] == 'deploy' else 'validated'
            job['log'] = output
            if job['action'] == 'validate':
                VALIDATIONS[(job['project_id'], ORG_ALIAS)] = job['review_digest']
    except (OSError, ValueError, RuntimeError, HTTPException, subprocess.TimeoutExpired) as exc:
        with STATE_LOCK:
            job['status'] = 'failed'
            job['log'] = (job.get('log', '') + '\n' if job.get('schema_deployed') else '') + (str(exc) if not isinstance(exc, subprocess.TimeoutExpired) else (
                'Salesforce operation timed out. Check the org deployment status before retrying.'
            ))


def queue_release(project_id, payload, request, tasks, action):
    authorize_release(request)
    if action == 'validate' and payload.sync_records:
        raise HTTPException(400, 'Check-only validation never syncs records')
    if payload.sync_records:
        from .procedure_sync import record_plan
        try:
            records = record_plan(project_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if records['review_digest'] != payload.record_digest:
            raise HTTPException(409, 'Review the current procedure record preview before syncing')
    if action == 'validate' and payload.assign_to_current_user:
        raise HTTPException(400, 'Validation does not assign permissions')
    try:
        plan, snapshot = permission_snapshot(project_id)
        bundle = reviewed_metadata_bundle(plan)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload.review_digest != snapshot['review_digest']:
        raise HTTPException(409, 'Review changed; reload the permission matrix')
    with STATE_LOCK:
        if any(job['status'] in {'queued', 'running'} for job in JOBS.values()):
            raise HTTPException(409, 'Another Salesforce release is running; wait for its result')
        key = (project_id, ORG_ALIAS)
        if action == 'deploy' and VALIDATIONS.get(key) != payload.review_digest:
            raise HTTPException(409, 'Validate this saved review before deploying')
        VALIDATIONS.pop(key, None)
        identifier = uuid.uuid4().hex
        job = {'job_id': identifier, 'project_id': project_id, 'org_alias': ORG_ALIAS,
               'review_digest': payload.review_digest, 'action': action, 'status': 'queued',
               'assign_to_current_user': payload.assign_to_current_user, 'sync_records': payload.sync_records,
               'record_digest': payload.record_digest, 'frontend_url': snapshot['frontend_url'], 'log': ''}
        JOBS[identifier] = job
        response = deepcopy(job)
    tasks.add_task(run_job, identifier, bundle)
    return response


@router.post('/api/projects/{project_id}/salesforce/validate', status_code=202)
def validate_release(project_id: str, payload: ReleaseRequest, request: Request, tasks: BackgroundTasks):
    return queue_release(project_id, payload, request, tasks, 'validate')


@router.post('/api/projects/{project_id}/salesforce/deploy', status_code=202)
def deploy_release(project_id: str, payload: ReleaseRequest, request: Request, tasks: BackgroundTasks):
    return queue_release(project_id, payload, request, tasks, 'deploy')


@router.get('/api/projects/{project_id}/salesforce/jobs/{job_id}')
def release_job(project_id: str, job_id: str, request: Request):
    if not local_request(request):
        raise HTTPException(403, 'Release jobs are available on the local workstation only')
    with STATE_LOCK:
        job = JOBS.get(job_id)
        if not job or job['project_id'] != project_id:
            raise HTTPException(404, 'Release job not found; server restarts clear browser job status')
        return deepcopy(job)


@router.get('/api/projects/{project_id}/salesforce/records')
def record_preview(project_id: str, request: Request):
    if not local_request(request):
        raise HTTPException(403, 'Record previews require the local builder')
    from .procedure_sync import record_plan, summary
    try:
        return summary(record_plan(project_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/api/projects/{project_id}/salesforce/publish')
def activate_existing_records(project_id: str, payload: ReleaseRequest, request: Request):
    """Adopt an older successful sync only after read-back verification."""
    authorize_release(request)
    from .procedure_sync import record_plan
    from .published_workspace import publish
    from .mim_incidents import query_salesforce
    with STATE_LOCK:
        if any(job['status'] in {'queued', 'running'} for job in JOBS.values()):
            raise HTTPException(409, 'Wait for the current Salesforce operation before publishing')
        try:
            records = record_plan(project_id)
            reviewed, snapshot = permission_snapshot(project_id)
            if payload.review_digest != snapshot['review_digest'] or payload.record_digest != records['review_digest']:
                raise HTTPException(409, 'Saved review or record preview changed; refresh and review again')
            key = records['batches'][0]['external_id']
            columns = sorted({name for batch in records['batches'] for row in batch['rows'] for name in row})
            rows = query_salesforce(f"SELECT Id, {', '.join(columns)} FROM {records['batches'][0]['object']} LIMIT 1001")
            expected = {row[key] for batch in records['batches'] for row in batch['rows']}
            if len(rows) > 1000 or not expected.issubset({row.get(key) for row in rows}):
                raise HTTPException(409, 'Not all reviewed procedure IDs exist in Salesforce. Deploy and sync before publishing.')
            _, current = permission_snapshot(project_id)
            if current['review_digest'] != payload.review_digest or record_plan(project_id)['review_digest'] != payload.record_digest:
                raise HTTPException(409, 'Review changed during verification; publication cancelled')
            value = publish(project_id, records, review=reviewed)
            return {'published': True, 'project_id': project_id, 'publication_digest': value['publication_digest']}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
