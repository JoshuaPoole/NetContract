'use strict';
let project = new URLSearchParams(location.search).get('project');
const get = id => document.getElementById(id);
get('askAlex').disabled=true;
async function post(url, payload={}) {
 const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-LifeAfterCode-Release':'1'},body:JSON.stringify(payload)});
 const data=await response.json();
 if (!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : 'Salesforce request failed');
 return data;
}
async function connectPublished() {
 try {
  const config=await post(project ? '/api/projects/'+encodeURIComponent(project)+'/alexa/config' : '/api/alexa/config');
  project=config.project_id;
  get('connection').textContent='Published Salesforce workspace · '+config.org_alias+' · '+config.object+' · published '+config.published_at;
  get('askAlex').disabled=false;
  try {
  const result=await post('/api/projects/'+encodeURIComponent(project)+'/alexa/incidents');
  get('incidentNotice').textContent=result.message;
  for (const record of result.records) {const option=document.createElement('option');option.value=record.id;option.textContent=record.label;get('incidentSelect').append(option);}
  } catch (error) {get('incidentNotice').textContent=error.message;}
 } catch (error) {get('connection').textContent=error.message;}
}
get('incidentSelect').addEventListener('change',()=>{if(get('incidentSelect').value)get('question').value='Find procedures for the selected incident';});
get('alexForm').addEventListener('submit', async event => {
 event.preventDefault();
 if (!project) return;
 get('askAlex').disabled=true; get('alexRecords').replaceChildren(); get('alexEvidence').textContent=''; get('alexStatus').textContent='Reading Salesforce…';
 try {
  const response=await fetch('/api/projects/'+encodeURIComponent(project)+'/alex/ask',{method:'POST',headers:{'Content-Type':'application/json','X-LifeAfterCode-Release':'1'},body:JSON.stringify({question:get('question').value,incident_record_id:get('incidentSelect').value || null})});
  const data=await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : 'Salesforce lookup failed');
  get('alexStatus').textContent=data.reply;
  for (const record of data.records) {
   const section=document.createElement('section'); section.className='card';
   const heading=document.createElement('h2'); heading.textContent=record.values.title || record.procedure_id; section.append(heading);
   const source=document.createElement('p'); source.textContent='Salesforce record: '+record.record_id+' · Procedure: '+record.procedure_id+' · Modified: '+(record.last_modified || 'unknown');section.append(source);
   const values=document.createElement('pre');values.style.whiteSpace='pre-wrap';values.textContent=JSON.stringify(record.values,null,2);section.append(values);
   get('alexRecords').append(section);
  }
  get('alexEvidence').textContent=JSON.stringify(data,null,2);
 } catch (error) {get('alexStatus').textContent=error.message;}
 finally {get('askAlex').disabled=false;}
});

const workspaceReady=connectPublished();
