'use strict';
const $ = id => document.getElementById(id);
let projectId = null, reviewPlan = null, discoveryResult = null, revision = 0;
const roleLabels = {incident:'Incident',dip:'Procedure (DIP / MOP / SOP / runbook)',workflow:'Workflow',execution_policy:'Execution policy',approval_rule:'Approval rule'};
function appendText(parent, tag, value) { const node = document.createElement(tag); node.textContent = value; parent.append(node); return node; }
function addRow(body, values) { const row = document.createElement('tr'); values.forEach(value => appendText(row,'td',String(value ?? '—'))); body.append(row); }
function list(id, values) { $(id).replaceChildren(); values.forEach(value => appendText($(id),'li',value)); }
async function readResponse(response) { if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(typeof error.detail === 'string' ? error.detail : 'Request failed (' + response.status + ')'); } return response.json(); }
function download(blob, filename) { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href=url; anchor.download=filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url),1000); }

