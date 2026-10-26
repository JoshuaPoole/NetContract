let permissionSnapshot = null;
let recordSnapshot = null;
let recordPreviewError = '';
function recordSyncPrerequisite() {
 const entity = reviewPlan?.entities.find(item=>item.concept==='DIP');
 if (!entity || entity.status!=='approved') return 'Approve the Procedure entity to enable record sync.';
 const keys = entity.fields.filter(field=>field.status==='approved' && field.external_id);
 if (keys.length!==1) return 'Approve exactly one procedure ID (such as dip_id) and select its unique external ID checkbox. linked_kba_id is a knowledge link, not a procedure ID.';
 if (!reviewSaved) return 'Save your current approvals to load the record sync preview.';
 return recordSnapshot ? '' : (recordPreviewError || 'Loading record preview; save and retry if it does not appear.');
}

let permissionRequest = 0;
let releaseBusy = false;
let releaseValidated = false;
let frontendDirty = false;
let frontendSaving = false;
let frontendVersion = 0;

function updateReleaseButtons() {
 const ready = permissionSnapshot?.deployment_enabled && reviewSaved && !frontendDirty && !frontendSaving && !reviewSaving && !releaseBusy;
 $('validateSalesforce').disabled = reviewSaving || releaseBusy || frontendDirty || frontendSaving || !approvedFields();
 $('deploySalesforce').disabled = !ready || !releaseValidated;
 $('assignPermissionSet').disabled = releaseBusy;
 const syncReason = recordSyncPrerequisite();
 $('activatePublishedRecords').disabled = releaseBusy || reviewSaving || !recordSnapshot || !reviewSaved;
 $('syncProcedureRecords').disabled = releaseBusy || !!syncReason || !recordSnapshot || !reviewSaved;
 $('syncProcedureRecords').setAttribute('title', releaseBusy ? 'Wait for the current Salesforce operation.' : syncReason || 'Ready to sync the previewed records after deployment.');
 if (releaseBusy) $('recordSyncNotice').textContent = 'Wait for the current Salesforce operation to finish.';
 else if (syncReason) $('recordSyncNotice').textContent = syncReason;
 else if (recordSnapshot) $('recordSyncNotice').textContent = 'Ready: ' + recordSnapshot.record_count + ' records → ' + recordSnapshot.object + ' · match by ' + recordSnapshot.external_id + '. Select the checkbox to include record sync with deployment.';
 $('saveAndValidate').disabled = reviewSaving || releaseBusy || frontendDirty || frontendSaving || !approvedFields();
 $('frontendUrl').disabled = releaseBusy || frontendSaving;
 $('saveFrontend').disabled = releaseBusy || frontendSaving;
}
function invalidateBrowserDeployment() {
 permissionRequest++;
 permissionSnapshot = null;
 recordSnapshot = null;
 recordPreviewError = '';
 $('syncProcedureRecords').checked = false;
 $('recordSyncNotice').textContent = 'Save the Procedure review to preview record updates.';
 releaseValidated = false;
 $('objectPermissions').replaceChildren();
 $('fieldPermissions').replaceChildren();
 $('permissionIdentity').textContent = '';
 $('permissionNotice').textContent = 'Save approved mappings to refresh the permissions matrix.';
 if (!releaseBusy) {
  $('releaseNotice').textContent = 'Save the current review and validate before deployment.';
  $('releaseLog').textContent = '';
 }
 updateReleaseButtons();
}
async function refreshPermissionMatrix() {
 if (!reviewSaved || frontendDirty || frontendSaving) return;
 const requestedProject = projectId, requestRevision = revision;
 const requestNumber = ++permissionRequest;
 try {
  const result = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/salesforce/permissions'));
  if (requestedProject !== projectId || requestRevision !== revision || requestNumber !== permissionRequest) return;
  permissionSnapshot = result;
  try {
   const records = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/salesforce/records'));
   if (requestedProject !== projectId || requestRevision !== revision || requestNumber !== permissionRequest) return;
   recordSnapshot = records;
   recordPreviewError = '';
   $('recordSyncNotice').textContent = records.record_count + ' records → ' + records.object + ' · match by ' + records.external_id + ' · fields: ' + records.fields.join(', ');
  } catch (error) {
   if (requestedProject !== projectId || requestRevision !== revision || requestNumber !== permissionRequest) return;
   recordSnapshot = null;
   recordPreviewError = error.message;
   $('recordSyncNotice').textContent = error.message;
  }
  releaseValidated = false;
  const access = value => value === 'true' ? 'Yes' : 'No';
  $('objectPermissions').replaceChildren();
  for (const object of result.objects) addRow($('objectPermissions'), [object.object, ...['allowRead','allowCreate','allowEdit','allowDelete','modifyAllRecords','viewAllRecords'].map(key => access(object[key]))]);
  $('fieldPermissions').replaceChildren();
  for (const field of result.fields) addRow($('fieldPermissions'), [field.field, access(field.readable), access(field.editable)]);
  $('permissionIdentity').textContent = 'Permission set: ' + result.permission_set + ' · Lightning app: ' + result.application + ' · Object tabs: ' + result.objects.length + (result.frontend_url ? ' · MIM Workspace: ' + result.frontend_url : ' · No hosted frontend selected');
  $('permissionNotice').textContent = result.message;
  $('releaseNotice').textContent = result.deployment_enabled ? 'Ready to check against ' + result.org_alias + '. Inspect the permission scope below.' : result.message;
  updateReleaseButtons();
 } catch (error) {
  if (requestedProject === projectId && requestRevision === revision && requestNumber === permissionRequest) {
   invalidateBrowserDeployment();
   $('permissionNotice').textContent = error.message;
   $('releaseNotice').textContent = error.message;
  }
 }
}
function freezeReview(busy) {
 releaseBusy = busy;
 for (const control of $('reviewEntities').querySelectorAll('input,select')) control.disabled = busy;
 $('saveReview').disabled = busy || !reviewPlan?.entities.length;
 updateReleaseButtons();
}
async function startSalesforceRelease(action) {
 if (releaseBusy) return;
 if (!permissionSnapshot?.deployment_enabled) {
  $('releaseNotice').textContent = permissionSnapshot?.message || 'Permissions could not be loaded. Save and check again; inspect the permissions message below.';
  return;
 }
 if (action === 'deploy' && !releaseValidated) {
  $('releaseNotice').textContent = 'Validate the current saved approvals before deploying.';
  return;
 }
 const requestedProject = projectId, requestRevision = revision;
 const snapshot = permissionSnapshot;
 const syncRecords = action === 'deploy' && $('syncProcedureRecords').checked;
 if (syncRecords && !recordSnapshot) { $('releaseNotice').textContent='Save the review and inspect the record preview before syncing.'; return; }
 const assignment = action === 'deploy' && $('assignPermissionSet').checked;
 releaseValidated = false;
 freezeReview(true);
 $('releaseLog').textContent = '';
 $('releaseNotice').textContent = (action === 'validate' ? 'Validating in ' : 'Validating and deploying to ') + snapshot.org_alias + '…';
 try {
  const base = '/api/projects/' + encodeURIComponent(projectId) + '/salesforce/';
  let job = await readResponse(await fetch(base + action, {
   method: 'POST', headers: {'Content-Type': 'application/json', 'X-LifeAfterCode-Release': '1'},
   body: JSON.stringify({org_alias: snapshot.org_alias, review_digest: snapshot.review_digest, assign_to_current_user: assignment, sync_records: syncRecords, record_digest: syncRecords ? recordSnapshot.record_digest : null}),
  }));
  while (job.status === 'queued' || job.status === 'running') {
   await new Promise(resolve => setTimeout(resolve, 1000));
   job = await readResponse(await fetch(base + 'jobs/' + encodeURIComponent(job.job_id)));
   if (requestedProject !== projectId || requestRevision !== revision) return;
  }
  if (requestedProject !== projectId || requestRevision !== revision) return;
  $('releaseLog').textContent = job.log || '';
  if (job.status === 'failed') throw new Error(job.schema_deployed ? 'Schema deployed, but procedure record sync failed. Inspect the operation result before retrying.' : 'Salesforce did not confirm success. See the operation result below.');
  if (action === 'validate' && job.status !== 'validated') throw new Error('Unexpected validation result; validate again before deployment.');
  if (action === 'deploy' && job.status !== 'deployed') throw new Error('Deployment was not confirmed. Check Salesforce before retrying.');
  releaseValidated = job.status === 'validated';
  $('releaseNotice').textContent = releaseValidated ? 'Validation succeeded. Deployment is now available for this saved review.' : (syncRecords ? 'Schema deployed and reviewed procedure records synced successfully.' : 'Deployment succeeded and approved fields were verified. Record sync was not selected.');
 } catch (error) {
  if (requestedProject === projectId && requestRevision === revision) $('releaseNotice').textContent = error.message;
 } finally {
  freezeReview(false);
 }
}
async function loadFrontendSettings() {
 const requestedProject = projectId, version = frontendVersion;
 try {
  const result = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/salesforce/frontend'));
  if (requestedProject !== projectId || version !== frontendVersion) return;
  $('frontendUrl').value = result.frontend_url;
  frontendDirty = false;
  showFrontendLink(result.frontend_url);
 } catch (error) {
  if (requestedProject === projectId) $('frontendNotice').textContent = error.message;
 }
}
function showFrontendLink(url) {
 $('previewFrontend').hidden = !url;
 if (url) $('previewFrontend').href = url;
 $('frontendNotice').textContent = url ? 'Saved. The next validation includes a MIM Workspace tab for this frontend. Its existing login and request handlers are reused.' : 'No hosted frontend selected. Deployment includes Salesforce record tabs only.';
}
async function saveFrontendSettings() {
 if (!projectId || releaseBusy || frontendSaving) return;
 const requestedProject = projectId, version = frontendVersion;
 frontendSaving = true;
 invalidateBrowserDeployment();
 updateReleaseButtons();
 try {
  const result = await readResponse(await fetch('/api/projects/' + encodeURIComponent(projectId) + '/salesforce/frontend', {
   method: 'PUT', headers: {'Content-Type': 'application/json', 'X-LifeAfterCode-Release': '1'},
   body: JSON.stringify({frontend_url: $('frontendUrl').value.trim()}),
  }));
  if (requestedProject !== projectId || version !== frontendVersion) return;
  $('frontendUrl').value = result.frontend_url;
  frontendDirty = false;
  showFrontendLink(result.frontend_url);
 } catch (error) {
  if (requestedProject === projectId) $('frontendNotice').textContent = error.message;
 } finally {
  frontendSaving = false;
  updateReleaseButtons();
 }
 if (requestedProject === projectId && !frontendDirty && reviewSaved && approvedFields()) await refreshPermissionMatrix();
}
$('frontendUrl').addEventListener('input', () => {
 frontendVersion++;
 frontendDirty = true;
 invalidateBrowserDeployment();
 $('previewFrontend').hidden = true;
 $('frontendNotice').textContent = 'Save this frontend URL before checking or deploying the mappings.';
 $('releaseNotice').textContent = 'Save the frontend URL first, then validate again.';
});
$('saveFrontend').addEventListener('click', saveFrontendSettings);
$('validateSalesforce').addEventListener('click', validateCurrentReview);
$('deploySalesforce').addEventListener('click', () => startSalesforceRelease('deploy'));

// Start only after the review AND deployment helpers are initialized.
const reviewReady = loadReview();

$('activatePublishedRecords').addEventListener('click', async ()=>{
 if (releaseBusy || !recordSnapshot || !permissionSnapshot || !reviewSaved) return;
 const project=projectId, currentRevision=revision;
 freezeReview(true);
 $('publicationNotice').textContent='Verifying previously synced Salesforce records…';
 try {
  await readResponse(await fetch('/api/projects/'+encodeURIComponent(project)+'/salesforce/publish',{
   method:'POST',headers:{'Content-Type':'application/json','X-LifeAfterCode-Release':'1'},
   body:JSON.stringify({review_digest:permissionSnapshot.review_digest,record_digest:recordSnapshot.record_digest}),
  }));
  if(project===projectId && currentRevision===revision) $('publicationNotice').textContent='Published. Open Alexa to query these Salesforce records. Later draft changes stay in the builder until republished.';
 } catch(error) {if(project===projectId) $('publicationNotice').textContent=error.message;}
 finally {freezeReview(false);}
});
