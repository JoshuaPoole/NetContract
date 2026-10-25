const status = document.querySelector('#status');
const output = document.querySelector('#result');
const select = document.querySelector('#incidents');
const refresh = document.querySelector('#refresh');
const review = document.querySelector('#recommend');
let busy = false;
function renderDecision(data) {
    const summary = document.querySelector('#decisionSummary');
    if (summary) {
        const network = data.network_evidence;
        summary.textContent = (data.plan ? `Recommended for review: ${data.plan.title || data.plan.dip_id}. ` : 'No unique supported recommendation. ')
            + (network ? `Synthetic node evidence: ${network.observation_record_id}, age ${Math.round(network.age_seconds)} seconds. ` : '')
            + (data.recommendation?.reason || '');
    }
    output.textContent = JSON.stringify(data, null, 2);
}
function controls() { refresh.disabled = busy; review.disabled = busy || !select.value; select.disabled = busy; }
async function post(path, payload) {
    const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-LifeAfterCode-Release': '1'}, body: JSON.stringify(payload || {})});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request failed');
    return result;
}
refresh.addEventListener('click', async () => {
    busy = true; controls(); output.textContent = ''; if (document.querySelector('#decisionSummary')) document.querySelector('#decisionSummary').textContent = ''; select.replaceChildren(); status.textContent = 'Reading Salesforce…';
    try {
        const data = await post('/api/mim/incidents');
        for (const row of data.records) {
            const option = document.createElement('option'); option.value = row.id;
            option.textContent = `${row.title || row.id} — ${row.service || 'Service missing'}`; select.append(option);
        }
        status.textContent = data.records.length ? `${data.records.length} recent records from ${data.object}. Select an incident to reread it and review its evidence.` : 'No readable incident records. Add or import records into the configured object first.';
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; controls(); }
});
select.addEventListener('change', () => { output.textContent = ''; if (document.querySelector('#decisionSummary')) document.querySelector('#decisionSummary').textContent = ''; controls(); });
review.addEventListener('click', async () => {
    busy = true; controls(); output.textContent = ''; if (document.querySelector('#decisionSummary')) document.querySelector('#decisionSummary').textContent = ''; status.textContent = 'Reading current incident and matching approved DIPs…';
    try { const data = await post('/api/mim/recommend', {record_id: select.value}); renderDecision(data); status.textContent = 'Review only. No approval, record update or recovery command was executed.'; }
    catch (error) { status.textContent = error.message; }
    finally { busy = false; controls(); }
});

// Accept one explicitly selected record only from an operator-configured parent.
// The backend treats this browser snapshot as advisory input, never as approval.
let parentOrigins = [];
fetch('/api/mim/bridge').then(response => response.ok ? response.json() : null)
    .then(config => {
        parentOrigins = config?.parent_origins || [];
        if (window.parent !== window) for (const origin of parentOrigins) {
            window.parent.postMessage({type: 'lifeaftercode.ready.v1'}, origin);
        }
    })
    .catch(() => { status.textContent = 'Hosted bridge configuration unavailable; no Salesforce messages accepted.'; });
window.addEventListener('message', async event => {
    if (event.source !== window.parent || !parentOrigins.includes(event.origin) ||
        event.data?.type !== 'lifeaftercode.incident.v1' || busy) return;
    busy = true; controls(); output.textContent = ''; if (document.querySelector('#decisionSummary')) document.querySelector('#decisionSummary').textContent = ''; status.textContent = 'Reviewing the selected Salesforce snapshot…';
    try {
        const record = {...event.data.record};
        delete record.attributes;
        const data = await post('/api/mim/advise-snapshot', {object: event.data.object, record});
        renderDecision(data);
        status.textContent = 'Advisory recommendation from the selected Salesforce snapshot. No update, approval or recovery command was executed.';
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; controls(); }
});
