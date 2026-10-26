let reviewRows = [];
$('showSyncIdentity').addEventListener('click', ()=>{
 const identity = reviewRows.find(item=>item.entity.concept==='DIP' && item.field.evidence.includes('#') && ['procedure_id','dip_id','mop_id','sop_id','runbook_id','id'].includes(item.field.source.split('.').pop()));
 if (!identity) { $('recordSyncNotice').textContent='No procedure ID was found in this scan. Rescan the ZIP containing the procedure catalogs.'; return; }
 identity.row.setAttribute('tabindex','-1'); identity.row.scrollIntoView?.({behavior:'smooth',block:'center'}); identity.row.focus?.();
 $('reviewNotice').textContent='For record sync, approve the Procedure entity and '+identity.field.source.split('.').pop()+', select its unique external ID checkbox, then save. linked_kba_id is a knowledge link, not a procedure ID.';
});
let procedureCatalogs = [];
function renderProcedures(catalogs) {
 procedureCatalogs = catalogs || [];
 $('procedureRows').replaceChildren();
 const counts = {};
 let total = 0;
 for (const catalog of procedureCatalogs) {
  for (const item of catalog.records) {
   total++; counts[item.procedure_type] = (counts[item.procedure_type] || 0) + 1;
   const record = item.record;
   const steps = ['implementation_steps','steps','actions','validation_steps','rollback_steps'].filter(key=>Array.isArray(record[key])).map(key=>key.replaceAll('_',' ') + ': ' + record[key].length).join(' · ');
   addRow($('procedureRows'), [item.procedure_type, item.procedure_id, item.title, typeof item.service === 'string' ? item.service : '—', steps, item.source_file + '#' + item.reference]);
  }
 }
 $('procedureSummary').textContent = total ? total + ' discovered procedures · ' + Object.entries(counts).map(([kind,count])=>count+' '+kind).join(' · ') + '. Review their shared schema below.' : 'No structured procedure catalogs in this saved scan. If you uploaded before this update, rescan the ZIP to discover DIPs, MOPs and SOPs.';
 $('exportProcedures').disabled = !total;
}
$('exportProcedures').addEventListener('click', ()=>{
 if (!procedureCatalogs.length) return;
 download(new Blob([JSON.stringify({concept:'Procedure',catalogs:procedureCatalogs,execution_enabled:false},null,2)],{type:'application/json'}),'discovered-procedures.json');
});
let reviewSaving = false;
let reviewSaved = false;
function changed() { reviewSaved=false; invalidateBrowserDeployment(); revision++; $('exportMetadata').disabled=true; $('reviewNotice').textContent='Unsaved changes. Save the review before exporting.'; updateReviewSummary(); }
function approvedFields() { return (reviewPlan?.entities || []).filter(entity=>entity.status==='approved').reduce((count,entity)=>count+entity.fields.filter(field=>field.status==='approved').length,0); }
function decision(value, onChange, label) { const select=document.createElement('select'); select.setAttribute('aria-label',label); for (const status of ['review','approved','rejected']) { const option=document.createElement('option'); option.value=status; option.textContent=status; select.append(option); } select.value=value; select.addEventListener('change',()=>{onChange(select.value); changed();}); return select; }
function renderReview(plan, saved) {
 invalidateBrowserDeployment(); reviewSaved=saved; reviewPlan=plan; $('reviewEntities').replaceChildren(); reviewRows=[];
 for (const entity of plan.entities) {
  const section=document.createElement('section'); section.className='entity'; appendText(section,'h3',entity.concept==='DIP' ? 'Procedure (DIP / MOP / SOP / runbook)' : entity.concept);
  section.append(decision(entity.status,value=>{entity.status=value;},entity.concept+' entity decision'));
  appendText(section,'p','Source models: '+entity.source_representations.join(', ')); appendText(section,'small',entity.evidence.join(' · '));
  const wrapper=document.createElement('div'); wrapper.className='scroll'; const table=document.createElement('table'); const head=document.createElement('thead'); const heading=document.createElement('tr'); ['Source field','Salesforce field','Type','PI candidate','Evidence','Decision'].forEach(text=>appendText(heading,'th',text)); head.append(heading); table.append(head); const body=document.createElement('tbody');
  for (const field of entity.fields) { const row=document.createElement('tr'); appendText(row,'td',field.source.split('.').pop());row.children[0].setAttribute('title',field.source); const cell=document.createElement('td'); const target=document.createElement('input'); target.value=field.target; target.setAttribute('aria-label',field.source+' Salesforce target'); target.addEventListener('input',()=>{field.target=target.value;changed();}); cell.append(target);row.append(cell);const typeCell = appendText(row,'td',field.data_type);
   if (entity.concept === 'DIP' && field.evidence.includes('#') && ['procedure_id','dip_id','mop_id','sop_id','runbook_id','id'].includes(field.source.split('.').pop()) && field.data_type === 'Text') {
    const label=document.createElement('label'); const key=document.createElement('input'); key.type='checkbox'; key.checked=!!field.external_id;
    key.setAttribute('aria-label',field.source+' unique external ID'); key.addEventListener('change',()=>{field.external_id=key.checked;changed();});
    label.append(key); appendText(label,'span','Unique external ID for record updates'); typeCell.append(label);
   }appendText(row,'td',field.pii_candidate?'Review':'No name signal');appendText(row,'td',field.evidence); const state=document.createElement('td');state.append(decision(field.status,value=>{field.status=value;},field.source+' field decision'));row.append(state);body.append(row); reviewRows.push({row,field,entity}); }
  table.append(body);wrapper.append(table);section.append(wrapper);$('reviewEntities').append(section);
 }
 $('saveReview').disabled=!plan.entities.length; $('exportMetadata').disabled=!saved || !approvedFields();
 updateReviewSummary();
 if (saved && approvedFields()) refreshPermissionMatrix();
 $('reviewNotice').textContent=plan.entities.length ? 'Review each entity and field. Saving does not deploy to Salesforce.' : 'No supported business entity models or procedure catalog schemas with fields were found. Other discovered business symbols remain available on the discovery page; no Salesforce schema is invented.';
}

function updateReviewSummary() {
 const entities = reviewPlan?.entities || [];
 const approvedEntities = entities.filter(entity => entity.status === 'approved');
 const selected = entities.reduce((count, entity) => count + entity.fields.filter(field => field.status === 'approved').length, 0);
 const eligible = approvedFields();
 $('reviewSummary').textContent = approvedEntities.length + ' approved entities · ' + selected + ' selected fields · ' + eligible + ' fields ready for Salesforce.' + (selected > eligible ? ' Approve the parent entity for the remaining selected fields.' : '');
 updateReleaseButtons();
}
async function saveCanonicalReview() {
 if (!projectId || !reviewPlan || releaseBusy || reviewSaving) return false;
 if (frontendDirty || frontendSaving) { $('releaseNotice').textContent='Save the frontend URL first, then check the reviewed mappings.'; return false; }
 const selectedRecordSync = $('syncProcedureRecords').checked;
 const selectedRecordDigest = recordSnapshot?.record_digest;
 reviewSaved = false;
 reviewSaving = true;
 invalidateBrowserDeployment();
 const requestedProject = projectId, requestRevision = revision;
 const payload = JSON.stringify(reviewPlan);
 $('saveReview').disabled = true;
 $('saveAndValidate').disabled = true;
 $('exportMetadata').disabled = true;
 try {
  const result = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/canonical/review', {
   method: 'PUT', headers: {'Content-Type': 'application/json'}, body: payload,
  }));
  if (requestedProject !== projectId || requestRevision !== revision) return false;
  $('reviewNotice').textContent = 'Review saved against source evidence. ' + result.approved_entities + ' entities contain approved fields.';
  $('exportMetadata').disabled = !approvedFields();
  reviewSaved = true;
  if (approvedFields()) await refreshPermissionMatrix();
  if (selectedRecordSync && selectedRecordDigest && recordSnapshot?.record_digest === selectedRecordDigest && requestedProject === projectId && requestRevision === revision) $('syncProcedureRecords').checked = true;
  return requestedProject === projectId && requestRevision === revision;
 } catch (error) {
  if (requestedProject === projectId && requestRevision === revision) $('reviewNotice').textContent = error.message;
  return false;
 } finally {
  reviewSaving = false;
  if (requestedProject === projectId && reviewPlan) {
   $('saveReview').disabled = !reviewPlan.entities.length;
   updateReviewSummary();
  }
 }
}
$('saveReview').addEventListener('click', saveCanonicalReview);
async function validateCurrentReview() {
 if (releaseBusy || reviewSaving) return;
 if (!approvedFields()) {
  updateReviewSummary();
  $('releaseNotice').textContent = 'Approve the parent entity and at least one field before checking Salesforce.';
  return;
 }
 if (!await saveCanonicalReview()) return;
 if (!permissionSnapshot) {
  $('releaseNotice').textContent = 'The review was saved, but permissions could not be loaded. Check the permissions message below and retry.';
  return;
 }
 await startSalesforceRelease('validate');
}
$('saveAndValidate').addEventListener('click', validateCurrentReview);
$('exportMetadata').addEventListener('click',async()=>{
 if(!projectId||$('exportMetadata').disabled)return;const requestedProject=projectId,requestRevision=revision;
 try {const response=await fetch('/api/projects/'+encodeURIComponent(projectId)+'/canonical/metadata.zip');if(!response.ok){await readResponse(response);return;}const blob=await response.blob();if(requestedProject!==projectId||requestRevision!==revision)return;download(blob,'lifeaftercode-salesforce-metadata.zip');$('reviewNotice').textContent='Reviewed Salesforce metadata downloaded. Inspect and deploy through the manual Salesforce workflow.';}
 catch(error){if(requestedProject===projectId&&requestRevision===revision)$('reviewNotice').textContent=error.message;}
});

async function loadReview() {
 projectId = new URLSearchParams(location.search).get('project');
 if (!projectId) {
  $('reviewNotice').textContent = 'Scan a repository on the discovery page first, then follow its Salesforce mappings link.';
  return;
 }
 $('alexWorkspaceLink').href = '/alex?project=' + encodeURIComponent(projectId);
 $('backToDiscovery').href = '/?project=' + encodeURIComponent(projectId);
 const requestedProject = projectId, requestRevision = revision;
 try {
  await loadFrontendSettings();
  if (requestedProject !== projectId || requestRevision !== revision) return;
  const review = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/canonical/candidates'));
  if (requestedProject === projectId && requestRevision === revision) { renderProcedures(review.procedure_catalogs); renderReview(review.review_plan, review.review_saved); }
 } catch (error) {
  if (requestedProject === projectId && requestRevision === revision) $('reviewNotice').textContent = error.message;
 }
}


