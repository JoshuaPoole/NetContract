import shutil
import subprocess
from pathlib import Path

import pytest


def test_voice_transcript_readout_and_evidence_remain_separate_from_diagnostics():
    if not shutil.which('node'):
        pytest.skip('Node needed for browser behavior checks')
    code=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {constructor(){this.value='';this.listeners={};this.children=[];this.checked=false;}addEventListener(k,f){this.listeners[k]=f;}append(x){this.children.push(x);}replaceChildren(){this.children=[];}}
const nodes={},get=id=>nodes[id]||(nodes[id]=new Element()),spoken=[],calls=[];
let recognizer;
class Recognition {constructor(){recognizer=this;}start(){}stop(){this.onend();}}
const window={SpeechRecognition:Recognition,isSecureContext:true,SpeechSynthesisUtterance:class{constructor(text){this.text=text;}},speechSynthesis:{cancel(){},speak(x){spoken.push(x.text);}}};
const context={window,URLSearchParams,location:{search:''},document:{getElementById:get,createElement:()=>new Element()},fetch:async(url,options)=>{
 calls.push({url,body:JSON.parse(options.body)});
 const data=url.endsWith('/config')?{project_id:'published',org_alias:'hackfest-developer',object:'DIP__c',published_at:'now'}:
 url.endsWith('/incidents')?{records:[],message:'Topic lookup available'}:
 {reply:'Read one Salesforce procedure.',status:'matches',publication_digest:'frozen',records:[{record_id:'SF-1',procedure_id:'BFD',values:{title:'BFD Session Down',implementation_steps:'["<inspect safely>"]'}}]};
 return {ok:true,json:async()=>data};
}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 await vm.runInContext('workspaceReady',context);
 assert.equal(get('voiceInput').disabled,false);
 get('speakReplies').checked=true;
 get('voiceInput').listeners.click();
 assert.equal(get('stopListening').disabled,false);
 recognizer.onresult({results:[[{transcript:'Find BFD procedures'}]]});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.at(-1).body.question,'Find BFD procedures');
 assert.match(spoken[0],/BFD Session Down/);
 assert.match(get('conversation').children[0].textContent,/You: Find BFD/);
 assert.match(get('conversation').children[1].textContent,/Alexa:/);
 assert.match(get('sessionEvents').textContent,/Lookup completed/);
 assert.match(get('diagnosticStatus').textContent,/No synthetic login or device commands/);
 const record=get('alexRecords').children[0];
 assert.equal(record.children[3].children[0].textContent,'<inspect safely>','procedure content must render as text');
 get('showEvidence').listeners.click();assert.equal(get('sourceDetails').open,true);
 recognizer.onend();assert.equal(get('voiceInput').disabled,false);
 get('voiceInput').listeners.click();recognizer.onerror({error:'not-allowed'});recognizer.onend();
 assert.equal(get('askAlex').disabled,false,'microphone errors must preserve typed input');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run(['node','-e',code,str(Path(__file__).resolve().parents[1]/'app/assets/alex.js')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_node_review_confirmation_and_logs_in_browser():
    if not shutil.which('node'):
        pytest.skip('Node needed for browser behavior checks')
    code=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element {constructor(){this.value='';this.listeners={};this.children=[];}addEventListener(k,f){this.listeners[k]=f;}append(x){this.children.push(x);}replaceChildren(){this.children=[];}}
const nodes={},get=id=>nodes[id]||(nodes[id]=new Element()),calls=[];
const fixture={session_id:'a'.repeat(32),version:1,evidence_digest:'b'.repeat(64),node:'NODE-00004',environment:'uat',environment_basis:'speaker + lab registry',phase:'awaiting_review',prechecks:{target_ip:'192.0.2.4',ansible_style_log:'SIMULATED PRECHECK'},postchecks:null,blockers:[],environment_note:'Explicit lab',task_plan:[{step_number:1,source_step:'Contain server',supported:true,module:'ansible.builtin.command',argv_preview:['netcontract-lab','isolate']}],task_log:null};
const context={window:{},URLSearchParams,location:{search:''},document:{getElementById:get,createElement:()=>new Element()},fetch:async(url,options)=>{
 const body=JSON.parse(options.body);calls.push({url,body});let data;
 if(url.endsWith('/config'))data={project_id:'p',org_alias:'hackfest-developer',object:'DIP__c',published_at:'now'};
 else if(url.endsWith('/incidents'))data={records:[],message:'No incident mapping'};
 else if(url.endsWith('/review')){
  if(body.confirmation_id){fixture.phase='simulated_recovery_verified';fixture.postchecks={ansible_style_log:'SIMULATED POSTCHECK'};fixture.task_log='SIMULATED TASK RESULTS';data={session:fixture,reply:'Simulated recovery only'};}
  else {fixture.phase='awaiting_confirmation';data={session:fixture,confirmation_id:'c'.repeat(32),reply:'Confirm simulation'};}
 }else data={reply:'Synthetic alert',status:'investigation',records:[],session:fixture};
 return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
 await vm.runInContext('workspaceReady',context);
 await vm.runInContext('ask("Investigate application exploitation on node 4 in UAT")',context);
 assert.match(get('diagnosticLogs').textContent,/PROPOSED TASKS/);
 assert.equal(get('reviewNode').disabled,false);assert.equal(get('confirmNode').disabled,true);
 await get('reviewNode').listeners.click();
 assert.equal(get('reviewNode').disabled,true);assert.equal(get('confirmNode').disabled,false);
 await get('confirmNode').listeners.click();
 assert.equal(calls.at(-1).body.confirmation_id,'c'.repeat(32));
 assert.match(get('diagnosticLogs').textContent,/SIMULATED POSTCHECK/);
 assert.match(get('diagnosticLogs').textContent,/SIMULATED TASK RESULTS/);
 assert.equal(get('confirmNode').disabled,true);
 const count=calls.length;await vm.runInContext('ask("show logs")',context);assert.equal(calls.length,count);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run(['node','-e',code,str(Path(__file__).resolve().parents[1]/'app/assets/alex.js')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
