import json
from copy import deepcopy

from fastapi import HTTPException
import pytest

from app import node_investigation as lab
from app import cyber_lab


@pytest.fixture(autouse=True)
def clean_sessions():
    lab.STATE.clear()
    lab.SESSIONS.clear()
    yield
    lab.STATE.clear()
    lab.SESSIONS.clear()


@pytest.fixture
def catalog():
    config = {'object':'Rtest_DIP__c','identity':'Dip_Id__c',
              'fields':{'Dip_Id__c':'dip_id','Title__c':'title','Steps__c':'implementation_steps'},
              'allowed_ids':['LAB-MOP-BFD','DIP-CYBER-001','DIP-CYBER-002','DIP-CYBER-003'],
              'publication_digest':'frozen'}
    steps = ['Confirm affected application, server, environment, and exposure path.',
             'Preserve relevant logs, alerts, source URLs, and forensic evidence.',
             'Contain the affected application or server using approved isolation controls.',
             'Identify exploited service, vulnerable version, or exposed integration.',
             'Apply approved patch, configuration correction, or compensating control.',
             'Rotate credentials, API tokens, or secrets that may have been exposed.',
             'Monitor for repeated exploit attempts or persistence indicators.']
    rows = [{'Id':f'SF-{i}','Dip_Id__c':identifier,'Title__c':identifier,
             'LastModifiedDate':'2026-10-26','Steps__c':json.dumps(steps if 'CYBER' in identifier else ['Inspect BFD session; review before intervention.'])}
            for i, identifier in enumerate(config['allowed_ids'])]
    return config, rows, lambda _: deepcopy(rows)


def act(config, query, session, token=None):
    return lab.review('p',config,session['session_id'],session['version'],session['evidence_digest'],query,token)


def test_bfd_node_three_parses_original_command_fixture(catalog):
    config,_,query = catalog
    s = lab.investigate('p', config,'List BFD alarms on node three in UAT',query)
    assert s['node']=='NODE-00003' and s['phase']=='awaiting_review'
    assert s['prechecks']['bfd_state']=='down'
    assert s['prechecks']['parsed_commands']['bfd_sessions']['fields']['peer_ip']=='192.0.2.4'
    assert not s['prechecks']['network_io'] and not s['execution_enabled']
    assert 'authentication not attempted' in s['prechecks']['ansible_style_log']
    assert 'confirmation' not in s
    approved = act(config,query,s)
    assert approved['session']['phase']=='awaiting_confirmation'
    done = act(config,query,s,approved['confirmation_id'])['session']
    assert done['phase']=='simulated_recovery_verified'
    assert done['postchecks']['bfd_state']=='up' and not done['postchecks']['alarms']
    with pytest.raises(HTTPException):
        act(config,query,s,approved['confirmation_id'])
    assert lab.investigate('p',config,'BFD node 3',query)['phase']=='review_blocked'


@pytest.mark.parametrize('question', ['BFD node 3 in production','BFD node 3 in moonbase','BFD nodes 1 and 3','BFD node 99','cyber node 1','endpoint compromise node 4'])
def test_unknown_ambiguous_and_cross_environment_targets_rejected(catalog,question):
    config,_,query = catalog
    with pytest.raises(ValueError):
        lab.investigate('p',config,question,query)
    assert not lab.SESSIONS


def test_cyber_steps_have_bounded_previews_then_explicit_simulated_results(catalog):
    config,_,query = catalog
    s=lab.investigate('p',config,'Application exploitation on node 4 in UAT',query)
    assert s['scenario']=='cyber' and s['procedure']['procedure_id']=='DIP-CYBER-001'
    assert len(s['task_plan'])==7 and all(t['supported'] for t in s['task_plan'])
    assert s['task_log'] is None and s['prechecks']['alarms'][0]['signal']=='cyber.application_exploitation'
    token=act(config,query,s)['confirmation_id']
    done=act(config,query,s,token)['session']
    assert 'command was not executed' in done['task_log']
    assert done['postchecks']['observation_state']=='clear'
    assert not done['execution_enabled']


def test_prose_is_never_interpolated_as_a_command_and_unknown_steps_block(catalog):
    tasks=cyber_lab.plan(['Apply patch; $(touch /tmp/nope)', 'Invent entirely new action'])
    assert tasks[0]['argv_preview']==['netcontract-lab','repair']
    assert not tasks[1]['supported'] and not tasks[1]['argv_preview']
    config,rows,query=catalog
    rows[1]['Steps__c']='["Invent entirely new action"]'
    s=lab.investigate('p',config,'cyber node 4',query)
    assert s['phase']=='review_blocked'
    with pytest.raises(HTTPException):
        act(config,query,s)


def test_missing_fields_or_published_environment_mismatch_block(catalog):
    config,rows,query=catalog
    rows[0]['Steps__c']=None
    assert lab.investigate('p',config,'BFD node 3',query)['phase']=='review_blocked'
    rows[0]['Steps__c']='["Inspect BFD"]'
    config['fields']['Env__c']='target_environment_order'
    rows[0]['Env__c']='["production"]'
    s=lab.investigate('p',config,'BFD node 3',query)
    assert s['procedure_environment_published'] and s['phase']=='review_blocked'


@pytest.mark.parametrize('change', ['procedure','publication','expired','token','overlap'])
def test_review_pins_evidence_procedure_publication_and_state(catalog,change):
    config,rows,query=catalog
    s=lab.investigate('p',config,'BFD node 3',query)
    token=act(config,query,s)['confirmation_id']
    if change=='procedure': rows[0]['Steps__c']='["Changed"]'
    if change=='publication': config['publication_digest']='new'
    if change=='expired': lab.SESSIONS[s['session_id']]['expires']=0
    if change=='token': token='0'*32
    if change=='overlap':
        other=lab.investigate('p',config,'BFD node 3',query)
        act(config,query,other,act(config,query,other)['confirmation_id'])
    with pytest.raises(HTTPException): act(config,query,s,token)


def test_local_api_requires_authorization_and_rejects_arbitrary_connection_fields(catalog,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import alex_workspace as alex
    config,_,query=catalog
    config.update(org_alias='hackfest-developer',incident=None)
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY','1')
    monkeypatch.setattr('shutil.which',lambda *a:'sf')
    monkeypatch.setattr(alex,'published',lambda *a:config)
    monkeypatch.setattr(alex,'query_salesforce',query)
    client=TestClient(app,base_url='http://localhost',client=('127.0.0.1',50000))
    headers={'Origin':'http://localhost','X-LifeAfterCode-Release':'1'}
    assert client.post('/api/projects/p/alex/ask',headers=headers,json={'question':'cyber node 4','password':'pretend'}).status_code==422
    session=client.post('/api/projects/p/alex/ask',headers=headers,json={'question':'application exploitation node 4'}).json()['session']
    body={'session_id':session['session_id'],'expected_version':session['version'],'evidence_digest':session['evidence_digest']}
    assert client.post('/api/projects/p/alexa/review',json=body).status_code==403
    approved=client.post('/api/projects/p/alexa/review',headers=headers,json=body)
    assert approved.status_code==200
    body['confirmation_id']=approved.json()['confirmation_id']
    done=client.post('/api/projects/p/alexa/review',headers=headers,json=body)
    assert done.status_code==200 and done.json()['session']['postchecks']['observation_state']=='clear'
