'use strict';
const project = new URLSearchParams(location.search).get('project');
const get = id => document.getElementById(id);
get('connection').textContent = project ? 'Source: Salesforce · hackfest-developer · approved builder project ' + project : 'Open Alex from your saved builder review so it can use the same object and field mappings.';
get('askAlex').disabled = !project;
if (project) get('builderLink').href='/salesforce?project='+encodeURIComponent(project);
get('alexForm').addEventListener('submit', async event => {
 event.preventDefault();
 if (!project) return;
 get('askAlex').disabled=true; get('alexRecords').replaceChildren(); get('alexEvidence').textContent=''; get('alexStatus').textContent='Reading Salesforce…';
 try {
  const response=await fetch('/api/projects/'+encodeURIComponent(project)+'/alex/ask',{method:'POST',headers:{'Content-Type':'application/json','X-LifeAfterCode-Release':'1'},body:JSON.stringify({question:get('question').value})});
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
