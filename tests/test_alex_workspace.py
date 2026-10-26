from fastapi.testclient import TestClient
import pytest

from app.main import app
from app import alex_workspace as alex
from app.reviewed_metadata import ReviewedCanonicalPlan


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('LIFEAFTERCODE_BROWSER_DEPLOY', '1')
    monkeypatch.setattr('shutil.which', lambda *a: 'sf')
    plan={'batches':[{'object':'Rtest_DIP__c','external_id':'Dip_Id__c','rows':[{'Dip_Id__c':'LAB-BFD'},{'Dip_Id__c':'DIP-CYBER'}]}]}
    review=ReviewedCanonicalPlan(repository='test',repository_id='hash',entities=[{
        'concept':'DIP','status':'approved','source_representations':['MOP'],'evidence':['data/mops.json#'],
        'fields':[{'source':'MOP.dip_id','target':'Dip_Id__c','status':'approved','evidence':'data/mops.json#/0/dip_id'},
                  {'source':'MOP.title','target':'Title__c','status':'approved','evidence':'data/mops.json#/0/title'},
                  {'source':'MOP.implementation_steps','target':'Implementation_Steps__c','status':'review','evidence':'data/mops.json#/0/implementation_steps'}]}])
    monkeypatch.setattr(alex,'record_plan',lambda _:plan)
    monkeypatch.setattr(alex,'load_saved_review',lambda _:review)
    client=TestClient(app,base_url='http://localhost',client=('127.0.0.1',50000))
    return client,{'Origin':'http://localhost','X-LifeAfterCode-Release':'1'}


def test_alex_reads_same_approved_object_and_never_invents_bfd_for_cyber(setup,monkeypatch):
    client,headers=setup
    queries=[]
    def query(text):
        queries.append(text)
        return [{'Id':'SF-BFD','Dip_Id__c':'LAB-BFD','Title__c':'BFD failure'},
                {'Id':'SF-CYBER','Dip_Id__c':'DIP-CYBER','Title__c':'Cyber containment changed in Salesforce','Secret__c':'hidden'}]
    monkeypatch.setattr(alex,'query_salesforce',query)
    r=client.post('/api/projects/demo/alex/ask',headers=headers,json={'question':'Investigate Cyber incident'})
    assert r.status_code==200
    data=r.json()
    assert data['source']=='salesforce'
    assert [row['record_id'] for row in data['records']]==['SF-CYBER']
    assert data['records'][0]['values']['title']=='Cyber containment changed in Salesforce'
    assert 'Secret__c' not in r.text and 'Implementation_Steps__c' not in queries[0]
    assert 'FROM Rtest_DIP__c' in queries[0]
    assert not data['execution_enabled']


def test_no_record_or_node_data_has_no_simulation_fallback(setup,monkeypatch):
    client,headers=setup
    monkeypatch.setattr(alex,'query_salesforce',lambda _:[])
    result=client.post('/api/projects/demo/alex/ask',headers=headers,json={'question':'BFD'}).json()
    assert result['status']=='no_match' and not result['records']
    node=client.post('/api/projects/demo/alex/ask',headers=headers,json={'question':'BFD on NODE-00001'}).json()
    assert node['status']=='clarification_required'
    assert not node['records']
    assert client.post('/api/projects/demo/alex/ask',json={'question':'BFD'}).status_code==403


def test_routes_share_the_builder_runtime(setup):
    client,_=setup
    assert client.get('/alex').status_code==200
    assert client.get('/alexa').text==client.get('/alex').text
