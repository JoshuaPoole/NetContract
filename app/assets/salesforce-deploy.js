let permissionSnapshot = null;
let permissionRequest = 0;
let releaseBusy = false;
let releaseValidated = false;
let frontendDirty = false;
let frontendSaving = false;
let frontendVersion = 0;

function updateReleaseButtons() {
 const ready = permissionSnapshot?.deployment_enabled && reviewSaved && !frontendDirty && !frontendSaving && !reviewSaving && !releaseBusy;
 $('validateSalesforce').disabled = !ready;
 $('deploySalesforce').disabled = !ready || !releaseValidated;
 $('assignPermissionSet').disabled = releaseBusy;
 $('saveAndValidate').disabled = reviewSaving || releaseBusy || frontendDirty || frontendSaving || !approvedFields();
 $('frontendUrl').disabled = releaseBusy || frontendSaving;
 $('saveFrontend').disabled = releaseBusy || frontendSaving;
}
function invalidateBrowserDeployment() {
 permissionRequest++;
 permissionSnapshot = null;
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
 if (releaseBusy || !permissionSnapshot?.deployment_enabled || (action === 'deploy' && !releaseValidated)) return;
 const requestedProject = projectId, requestRevision = revision;
 const snapshot = permissionSnapshot;
 const assignment = action === 'deploy' && $('assignPermissionSet').checked;
 releaseValidated = false;
 freezeReview(true);
 $('releaseLog').textContent = '';
 $('releaseNotice').textContent = (action === 'validate' ? 'Validating in ' : 'Validating and deploying to ') + snapshot.org_alias + '…';
 try {
  const base = '/api/projects/' + encodeURIComponent(projectId) + '/salesforce/';
  let job = await readResponse(await fetch(base + action, {
   method: 'POST', headers: {'Content-Type': 'application/json', 'X-LifeAfterCode-Release': '1'},
   body: JSON.stringify({org_alias: snapshot.org_alias, review_digest: snapshot.review_digest, assign_to_current_user: assignment}),
  }));
  while (job.status === 'queued' || job.status === 'running') {
   await new Promise(resolve => setTimeout(resolve, 1000));
   job = await readResponse(await fetch(base + 'jobs/' + encodeURIComponent(job.job_id)));
   if (requestedProject !== projectId || requestRevision !== revision) return;
  }
  if (requestedProject !== projectId || requestRevision !== revision) return;
  $('releaseLog').textContent = job.log || '';
  if (job.status === 'failed') throw new Error('Salesforce did not confirm success. See the operation result below.');
  if (action === 'validate' && job.status !== 'validated') throw new Error('Unexpected validation result; validate again before deployment.');
  if (action === 'deploy' && job.status !== 'deployed') throw new Error('Deployment was not confirmed. Check Salesforce before retrying.');
  releaseValidated = job.status === 'validated';
  $('releaseNotice').textContent = releaseValidated ? 'Validation succeeded. Deployment is now available for this saved review.' : 'Deployment succeeded and approved fields were verified.';
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
$('validateSalesforce').addEventListener('click', () => startSalesforceRelease('validate'));
$('deploySalesforce').addEventListener('click', () => startSalesforceRelease('deploy'));

// Start only after the review AND deployment helpers are initialized.
const reviewReady = loadReview();
