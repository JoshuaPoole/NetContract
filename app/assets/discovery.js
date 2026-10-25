let repositoryIR = null;

function renderRepositoryPreview(ir) {
 repositoryIR = ir;
 $('irNodes').replaceChildren();
 for (const node of ir.nodes) {
  const evidence = node.evidence.source_file + (node.evidence.reference !== undefined && node.evidence.reference !== null ? '#' + node.evidence.reference : (node.evidence.line ? ':' + node.evidence.line : ''));
  const fields = node.fields.map(field => field.source.split('.').pop()).join('\n');
  addRow($('irNodes'), [node.kind, node.name, evidence, fields || '—']);
 }
 $('irSummary').textContent = ir.nodes.length + ' source-backed candidates. Review their classification before Salesforce export.';
 $('irEmpty').hidden = ir.nodes.length > 0;
 list('irWarnings', ir.warnings);
 $('downloadIR').disabled = false;
}

function renderInventory(result) {
 const inventory=result.inventory; discoveryResult={repository:result.analysis.repository,repository_id:result.analysis.repository_id,ir:result.ir,...inventory};
 renderRepositoryPreview(result.ir);
 $('businessCount').textContent=inventory.business_contracts.length; $('resourceCount').textContent=inventory.terraform.resource_count; $('fileCount').textContent=inventory.terraform.files.length;
 $('businessRows').replaceChildren(); inventory.business_contracts.forEach(contract=>addRow($('businessRows'),[contract.name,roleLabels[contract.kind]||contract.kind,contract.evidence.map(item=>item.source_file+' · '+item.reference).join('\n'),'Needs review']));
 $('terraformRows').replaceChildren(); inventory.terraform.declarations.forEach(item=>addRow($('terraformRows'),[item.address,item.kind,item.resource_type,item.module_path,item.source_file+(item.line ? ':'+item.line : ' · JSON block path: '+item.address)]));
 $('businessEmpty').hidden=!!inventory.business_contracts.length; $('terraformEmpty').hidden=!!inventory.terraform.declarations.length;
 list('businessWarnings',inventory.business_warnings);list('terraformWarnings',inventory.terraform.warnings);list('terraformFiles',inventory.terraform.files);
 const seeds = inventory.seeded_network || {records: [], warnings: []};
 $('seedRows').replaceChildren();
 const counts = {};
 for (const row of seeds.records) counts[row.kind] = (counts[row.kind] || 0) + 1;
 for (const [kind, count] of Object.entries(counts)) addRow($('seedRows'), [kind, String(count), 'Synthetic · needs review']);
 $('seedSummary').textContent = seeds.records.length + ' seed records discovered. Export an import plan with a stable lab namespace before Salesforce upsert. Runtime generators are not executed.';
 list('seedWarnings', seeds.warnings);
 $('results').hidden=false; $('exportInventory').disabled=false;
}

function showDiscovery(result) {
 projectId = result.project_id;
 renderInventory(result);
 $('salesforceLink').href = '/salesforce?project=' + encodeURIComponent(projectId);
 $('salesforceLink').hidden = false;
}
$('scanForm').addEventListener('submit', async event => {
 event.preventDefault();
 const file = $('file').files[0];
 if (!file) return;
 revision++;
 const requestRevision = revision;
 projectId = null;
 discoveryResult = null;
 repositoryIR = null;
 $('downloadIR').disabled = true;
 $('results').hidden = true;
 $('salesforceLink').hidden = true;
 $('exportInventory').disabled = true;
 $('scanButton').disabled = true;
 $('notice').textContent = 'Inspecting business symbols and Terraform declarations…';
 try {
  const form = new FormData();
  form.append('file', file);
  const result = await readResponse(await fetch('/api/analyze', {method: 'POST', body: form}));
  if (requestRevision !== revision) return;
  showDiscovery(result);
  history.replaceState(null, '', '/?project=' + encodeURIComponent(projectId));
  $('notice').textContent = 'Discovery complete for ' + file.name + '. All findings are static observations.';
 } catch (error) {
  if (requestRevision === revision) $('notice').textContent = error.message;
 } finally {
  if (requestRevision === revision) $('scanButton').disabled = false;
 }
});
$('exportInventory').addEventListener('click', () => {
 if (discoveryResult) download(new Blob([JSON.stringify(discoveryResult, null, 2)], {type: 'application/json'}), 'lifeaftercode-discovery.json');
});
$('downloadIR').addEventListener('click', () => {
 if (repositoryIR) download(new Blob([JSON.stringify(repositoryIR, null, 2)], {type: 'application/json'}), 'lifeaftercode-repository-ir.json');
});
async function restoreDiscovery() {
 const id = new URLSearchParams(location.search).get('project');
 if (!id) return;
 const requestRevision = revision;
 $('notice').textContent = 'Loading saved discovery evidence…';
 try {
  const result = await readResponse(await fetch('/api/projects/' + encodeURIComponent(id) + '/discovery'));
  if (requestRevision !== revision) return;
  showDiscovery(result);
  $('notice').textContent = 'Saved source discovery loaded. All findings are static observations.';
 } catch (error) {
  if (requestRevision === revision) $('notice').textContent = error.message;
 }
}
const discoveryReady = restoreDiscovery();

