'use strict';
let project = new URLSearchParams(location.search).get('project');
const get = id => document.getElementById(id);
const browser = typeof window === 'undefined' ? {} : window;
const Recognition = browser.SpeechRecognition || browser.webkitSpeechRecognition;
let busy=false,connected=false,listening=false,recognition=null;
const history=[],events=[];
let latestEvidence=null;
function controls() {
 get('askAlex').disabled=!connected || busy || listening;
 get('voiceInput').disabled=!connected || busy || listening || !Recognition;
 get('stopListening').disabled=!listening;
 get('incidentSelect').disabled=busy || listening;
}
function logEvent(text) {
 events.push({at:new Date().toISOString(),message:text});
 get('sessionEvents').textContent=events.map(event=>event.at+' · '+event.message).join('\n');
 get('sessionEvents').scrollTop=get('sessionEvents').scrollHeight;
}
function bubble(text,user=false) {
 history.push({at:new Date().toISOString(),role:user?'user':'assistant',text});
 const element=document.createElement('div');element.className='bubble'+(user?' user':'');element.textContent=(user?'You: ':'Alexa: ')+text;
 get('conversation').append(element);get('conversation').scrollTop=get('conversation').scrollHeight;
}
function speak(text) {
 if (!get('speakReplies').checked) return;
 if (!browser.speechSynthesis || !browser.SpeechSynthesisUtterance) {get('voiceStatus').textContent='Read-out is unavailable in this browser. Replies remain visible.';return;}
 browser.speechSynthesis.cancel();
 const utterance=new browser.SpeechSynthesisUtterance(text);utterance.lang='en-AU';browser.speechSynthesis.speak(utterance);
}
async function post(url,payload={}) {
 const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-LifeAfterCode-Release':'1'},body:JSON.stringify(payload)});
 const data=await response.json();
 if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Salesforce request failed');
 return data;
}
async function connectPublished() {
 controls();logEvent('Opening published Salesforce workspace.');
 if (!Recognition) get('voiceStatus').textContent='Voice recognition is unavailable in this browser. Type your request; read-out may still be available.';
 try {
  const config=await post(project?'/api/projects/'+encodeURIComponent(project)+'/alexa/config':'/api/alexa/config');
  project=config.project_id;connected=true;
  get('connection').textContent='Published Salesforce workspace · '+config.org_alias+' · '+config.object+' · published '+config.published_at;
  logEvent('Connected to '+config.org_alias+' / '+config.object+'.');
  try {
   const result=await post('/api/projects/'+encodeURIComponent(project)+'/alexa/incidents');
   get('incidentNotice').textContent=result.message;
   for (const record of result.records) {const option=document.createElement('option');option.value=record.id;option.textContent=record.label;get('incidentSelect').append(option);}
   logEvent('Incident list read: '+result.records.length+' records.');
  } catch(error) {get('incidentNotice').textContent=error.message;logEvent('Incident read failed: '+error.message);}
 } catch(error) {get('connection').textContent=error.message;logEvent('Connection failed: '+error.message);}
 finally {controls();}
}
function renderRecord(record) {
 const section=document.createElement('section');section.className='card';
 const heading=document.createElement('h2');heading.textContent=record.values.title || record.procedure_id;section.append(heading);
 const source=document.createElement('p');source.textContent='Salesforce record: '+record.record_id+' · Procedure: '+record.procedure_id+' · Modified: '+(record.last_modified || 'unknown');section.append(source);
 for (const key of ['implementation_steps','validation_steps','rollback_steps']) {
  let value=record.values[key];if (!value) continue;
  if (typeof value==='string') {try {value=JSON.parse(value);} catch { /* Retain plain stored text. */ }}
  const title=document.createElement('h3');title.textContent=key.replaceAll('_',' ');section.append(title);
  if (Array.isArray(value)) {const list=document.createElement('ol');for(const step of value){const item=document.createElement('li');item.textContent=typeof step==='string'?step:JSON.stringify(step);list.append(item);}section.append(list);}
  else {const text=document.createElement('pre');text.textContent=typeof value==='string'?value:JSON.stringify(value,null,2);section.append(text);}
 }
 const details=document.createElement('details'),summary=document.createElement('summary'),values=document.createElement('pre');summary.textContent='All published fields';values.textContent=JSON.stringify(record.values,null,2);details.append(summary);details.append(values);section.append(details);
 get('alexRecords').append(section);
}
async function ask(question) {
 if (!project || !connected || busy || !question.trim()) return;
 busy=true;controls();bubble(question,true);logEvent('Request submitted to Salesforce procedure lookup.');
 get('alexRecords').replaceChildren();get('alexEvidence').textContent='';get('alexStatus').textContent='Reading Salesforce…';latestEvidence=null;
 try {
  const data=await post('/api/projects/'+encodeURIComponent(project)+'/alex/ask',{question,incident_record_id:get('incidentSelect').value || null});
  latestEvidence=data;get('alexStatus').textContent=data.reply;
  const titles=data.records.slice(0,3).map(record=>record.values.title || record.procedure_id);
  const reply=data.reply+(titles.length?' Matching procedures: '+titles.join('; ')+'.':'');
  bubble(reply);speak(reply);
  for(const record of data.records)renderRecord(record);
  get('alexEvidence').textContent=JSON.stringify(data,null,2);
  logEvent('Lookup completed: '+data.status+' · '+data.records.length+' displayed records · publication '+(data.publication_digest || 'unknown')+'.');
  get('diagnosticStatus').textContent='No synthetic login or device commands were run. Inspect the Salesforce source evidence and procedure steps above; these are not live diagnostic logs.';
 } catch(error) {get('alexStatus').textContent=error.message;bubble(error.message);logEvent('Lookup failed: '+error.message);}
 finally {busy=false;controls();}
}
get('incidentSelect').addEventListener('change',()=>{if(get('incidentSelect').value)get('question').value='Find procedures for the selected incident';});
get('alexForm').addEventListener('submit',event=>{event.preventDefault();return ask(get('question').value);});
get('showEvidence').addEventListener('click',()=>{get('sourceDetails').open=true;get('sourceDetails').scrollIntoView?.({behavior:'smooth',block:'nearest'});});
get('stopSpeech').addEventListener('click',()=>browser.speechSynthesis?.cancel());
get('speakReplies').addEventListener('change',()=>{if(!get('speakReplies').checked)browser.speechSynthesis?.cancel();});
get('voiceInput').addEventListener('click',()=>{
 if (!Recognition || busy || listening || !connected) return;
 if (!browser.isSecureContext) {get('voiceStatus').textContent='Microphone input requires localhost or HTTPS. Type your request instead.';return;}
 browser.speechSynthesis?.cancel();recognition=new Recognition();recognition.lang='en-AU';recognition.continuous=false;recognition.interimResults=false;
 listening=true;controls();get('voiceStatus').textContent='Listening…';logEvent('Microphone requested by user.');
 let submitted=false,failed=false;
 recognition.onresult=event=>{if(submitted)return;submitted=true;const text=event.results[0][0].transcript.slice(0,500);get('question').value=text;get('voiceStatus').textContent='Heard: '+text;listening=false;controls();ask(text);};
 recognition.onerror=event=>{failed=true;listening=false;controls();get('voiceStatus').textContent='Microphone: '+event.error+'. Typed input is still available.';logEvent('Microphone error: '+event.error);};
 recognition.onend=()=>{listening=false;if(!submitted && !failed)get('voiceStatus').textContent='Listening stopped. Type or try speaking again.';controls();};
 try {recognition.start();}catch(error){listening=false;controls();get('voiceStatus').textContent=error.message;}
});
get('stopListening').addEventListener('click',()=>recognition?.stop());
get('downloadSession').addEventListener('click',()=>{
 const blob=new Blob([JSON.stringify({project,history,events,evidence:latestEvidence,execution_enabled:false},null,2)],{type:'application/json'});
 const url=browser.URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='alexa-session-evidence.json';link.click();browser.URL.revokeObjectURL(url);
});
const workspaceReady=connectPublished();
