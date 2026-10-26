
from fastapi import HTTPException
import pytest

import test_procedure_sync as sync_tests
from app import alex_workspace as alex
from app.published_workspace import published
from app.procedure_sync import record_plan


@pytest.fixture
def workspace_setup(tmp_path, monkeypatch):
    return sync_tests.setup.__wrapped__(tmp_path, monkeypatch)


def payload_for(client, project):
    base=f'/api/projects/{project}/salesforce'
    return {'review_digest':client.get(base+'/permissions').json()['review_digest'],
            'record_digest':client.get(base+'/records').json()['record_digest']}


def test_verify_existing_sync_then_customer_reads_frozen_published_mapping(workspace_setup, monkeypatch):
    client, project, review, headers=workspace_setup
    records=record_plan(project)
    rows=[dict(row, Id='a00123456789012AAA') for batch in records['batches'] for row in batch['rows']]
    monkeypatch.setattr('app.mim_incidents.query_salesforce',lambda _:rows)
    assert client.post('/api/alexa/config',headers=headers,json={}).status_code==409
    base=f'/api/projects/{project}/salesforce'
    result=client.post(base+'/publish',headers=headers,json=payload_for(client,project))
    assert result.status_code==200,result.text
    original=published(project)
    assert published()['project_id']==project
    # Changing a saved draft cannot change the published customer schema.
    steps=next(f for f in review['entities'][0]['fields'] if f['source'].endswith('.implementation_steps'))
    steps['status']='rejected'
    assert client.put(f'/api/projects/{project}/canonical/review',json=review).status_code==200
    assert published(project)==original
    monkeypatch.setattr(alex,'query_salesforce',lambda _:rows)
    response=client.post('/api/alexa/ask',headers=headers,json={'question':'BFD'})
    assert response.status_code==200,response.text
    assert response.json()['records'][0]['values']['implementation_steps']=='["Inspect BFD"]'
    assert response.json()['publication_digest']==original['publication_digest']
    assert client.post('/api/alexa/config',json={}).status_code==403


def test_missing_records_cannot_publish_new_workspace(workspace_setup,monkeypatch):
    client,project,_,headers=workspace_setup
    monkeypatch.setattr('app.mim_incidents.query_salesforce',lambda _:[])
    response=client.post(f'/api/projects/{project}/salesforce/publish',headers=headers,json=payload_for(client,project))
    assert response.status_code==409
    with pytest.raises(HTTPException):
        published(project)


def test_customer_uses_selected_salesforce_incident_instead_of_typed_guess(workspace_setup,monkeypatch):
    client,_,_,headers=workspace_setup
    monkeypatch.setattr(alex,'published',lambda *a:{'project_id':'demo','object':'DIP__c',
        'identity':'Dip_Id__c','fields':{'Dip_Id__c':'dip_id','Title__c':'title'},
        'allowed_ids':['LAB-BFD','CYBER'],'publication_digest':'frozen',
        'incident':{'object':'Incident__c','fields':{'Summary__c':'short_description'}}})
    queries=[]
    def query(text):
        queries.append(text)
        if 'FROM Incident__c' in text:
            return [{'Id':'a00123456789012AAA','Summary__c':'BFD session failure'}]
        return [{'Id':'BFD-RECORD','Dip_Id__c':'LAB-BFD','Title__c':'BFD session inspection'},
                {'Id':'CYBER-RECORD','Dip_Id__c':'CYBER','Title__c':'Cyber response'}]
    monkeypatch.setattr(alex,'query_salesforce',query)
    response=client.post('/api/alexa/ask',headers=headers,json={'question':'Cyber','incident_record_id':'a00123456789012AAA'})
    assert response.status_code==200,response.text
    assert [r['record_id'] for r in response.json()['records']]==['BFD-RECORD']
    assert response.json()['incident']['record_id']=='a00123456789012AAA'
    assert "WHERE Id = 'a00123456789012AAA'" in queries[0]
    assert client.post('/api/alexa/ask',headers=headers,json={'question':'BFD','incident_record_id':"' OR Name != ''"}).status_code==422


def test_publication_written_after_confirmed_sync_only(workspace_setup,monkeypatch):
    from app import salesforce_browser as browser
    client,project,_,headers=workspace_setup
    monkeypatch.setattr(browser,'execute_release',lambda *a:'Schema verified')
    monkeypatch.setattr('scripts.seeded_network_sf.apply',lambda *a:[{'state':'JobComplete'}])
    data=payload_for(client,project)
    base=f'/api/projects/{project}/salesforce'
    assert client.post(base+'/validate',headers=headers,json={'review_digest':data['review_digest']}).status_code==202
    with pytest.raises(HTTPException):
        published(project)
    response=client.post(base+'/deploy',headers=headers,json={**data,'sync_records':True})
    job=client.get(base+'/jobs/'+response.json()['job_id']).json()
    assert job['status']=='deployed',job['log']
    assert published(project)['allowed_ids']==['LAB-1','LAB-2']
    assert 'Published Alexa workspace' in job['log']


def test_customer_page_opens_active_publication_and_sends_selected_incident():
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which('node'):
        pytest.skip('Node needed for browser script check')
    code=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {constructor(){this.value='';this.listeners={};this.children=[];}addEventListener(k,f){this.listeners[k]=f;}append(x){this.children.push(x);}replaceChildren(){this.children=[];}}
const elements={},calls=[];
const get=id=>elements[id]||(elements[id]=new Element());
const context={URLSearchParams,location:{search:''},document:{getElementById:get,createElement:()=>new Element()},fetch:async(url,options)=>{
 calls.push({url,body:JSON.parse(options.body)});
 const data=url.endsWith('/config')?{project_id:'published',org_alias:'hackfest-developer',object:'DIP__c',published_at:'now'}:
 url.endsWith('/incidents')?{records:[{id:'a00123456789012AAA',label:'BFD down'}],message:'Choose an incident'}:
 {reply:'Read Salesforce',records:[],publication_digest:'frozen'};
 return {ok:true,json:async()=>data};
}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 await vm.runInContext('workspaceReady',context);
 assert.equal(calls[0].url,'/api/alexa/config');
 assert.equal(get('askAlex').disabled,false);
 get('incidentSelect').value='a00123456789012AAA';
 get('incidentSelect').listeners.change();
 await get('alexForm').listeners.submit({preventDefault(){}});
 assert.equal(calls.at(-1).url,'/api/projects/published/alex/ask');
 assert.equal(calls.at(-1).body.incident_record_id,'a00123456789012AAA');
 assert.equal(get('alexStatus').textContent,'Read Salesforce');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run(['node','-e',code,str(Path(__file__).resolve().parents[1]/'app/assets/alex.js')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
