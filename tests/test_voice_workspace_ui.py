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
