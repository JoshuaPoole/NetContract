/* Exercise both pages with real shipped scripts and controlled API replies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let downloads = 0;
class Element {
 constructor(tag) { this.tag=tag; this.children=[]; this.attributes={}; this.listeners={}; this.disabled=false; }
 setAttribute(name,value) { this.attributes[name]=value; }
 append(child) { this.children.push(child); }
 replaceChildren() { this.children=[]; }
 addEventListener(event,fn) { this.listeners[event]=fn; }
 click() { downloads++; }
 remove() {}
 querySelectorAll() { const out=[];const visit=node=>{for(const child of node.children){if(['input','select'].includes(child.tag))out.push(child);visit(child);}};visit(this);return out; }
}
const plan={repository:'legacy.zip',repository_id:'hash123',entities:[{concept:'Incident',status:'review',source_representations:['Incident'],evidence:['models.py:1'],fields:[{source:'Incident.ticket',target:'Ticket__c',data_type:'Text',evidence:'models.py:2',pii_candidate:false,status:'review'}]}]};
const inventory={business_contracts:[{name:'<img src=x onerror=alert(1)>',kind:'incident',evidence:[{source_file:'models.py',reference:'line:1'}]}],business_warnings:[],terraform:{resource_count:1,files:['infra/main.tf'],declarations:[{address:'aws_instance.app',kind:'resource',resource_type:'aws_instance',module_path:'infra',source_file:'infra/main.tf',line:3}],warnings:[]}};
const ir={nodes:[{kind:'model_candidate',name:'<unsafe candidate>',evidence:{source_file:'models.py',line:2},fields:[{source:'Incident.ticket',proposed_target:'Ticket',proposed_type:'Text'}]}],warnings:['Static source evidence only']};
const result={project_id:'abc123',analysis:{repository:'legacy.zip',repository_id:'hash123'},inventory,ir};
let savedPlan, failSave=false, deferSave=null, deferCandidate=null;
let permissionsEnabled=false, releaseFails=false, releaseAction='validate';
const releaseCalls=[];
let savedFrontendUrl='';
function page(template, query='', delayDeploymentScript=false) {
 const html=fs.readFileSync(path.join(__dirname,'../app/',template),'utf8');
 const elements={};
 for (const match of html.matchAll(/id="([^"]+)"/g)) elements[match[1]]=new Element('div');
 const requests=[];
 const context={
  document:{getElementById:id=>elements[id]||null,createElement:tag=>new Element(tag),body:new Element('body')},
  URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>{}}, URLSearchParams,
  location:{search:query},history:{replaceState(){}},Blob,FormData:class{append(){}},setTimeout:fn=>fn(),
  fetch:async(url,options={})=>{
   requests.push(url);
   if(url==='/api/analyze'||url.endsWith('/discovery'))return {ok:true,json:async()=>structuredClone(result)};
   if(url.endsWith('/salesforce/frontend')){if(options.method==='PUT')savedFrontendUrl=JSON.parse(options.body).frontend_url;return {ok:true,json:async()=>({frontend_url:savedFrontendUrl})};}
   if(url.endsWith('/salesforce/permissions'))return {ok:true,json:async()=>({deployment_enabled:permissionsEnabled,message:permissionsEnabled?'CLI ready':'CLI unavailable',review_digest:'a'.repeat(64),frontend_url:savedFrontendUrl,objects:[{object:'Incident__c',allowRead:'true',allowCreate:'true',allowEdit:'true',allowDelete:'false',modifyAllRecords:'false',viewAllRecords:'false'}],fields:[{field:'Incident__c.Ticket__c',readable:'true',editable:'true'}],org_alias:'hackfest-developer',permission_set:'TestAccess',application:'TestApp'})};
   if(url.endsWith('/salesforce/validate')||url.endsWith('/salesforce/deploy')){assert.equal(options.headers['X-LifeAfterCode-Release'],'1');releaseAction=url.split('/').pop();releaseCalls.push({action:releaseAction,...JSON.parse(options.body)});return {ok:true,json:async()=>({job_id:'job1',status:'queued'})};}
   if(url.endsWith('/salesforce/jobs/job1'))return {ok:true,json:async()=>({job_id:'job1',status:releaseFails?'failed':releaseAction==='validate'?'validated':'deployed',log:releaseFails?'Permission validation failed':'Operation verified'})};
   if(url.endsWith('/canonical/candidates')){if(deferCandidate)await deferCandidate;return {ok:true,json:async()=>({review_plan:structuredClone(plan),review_saved:false})};}
   if(url.endsWith('/canonical/review')){savedPlan=JSON.parse(options.body);if(deferSave)await deferSave;return {ok:!failSave,json:async()=>failSave?{detail:'Unverified evidence'}:{approved_entities:1}};}
   if(url.endsWith('/canonical/metadata.zip'))return {ok:true,blob:async()=>new Blob(['PK'])};
   throw Error('Unexpected API request: '+url);
  }
 };
 vm.createContext(context);
 const loadScript=name=>vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/assets/',name),'utf8'),context);
 for(const script of html.matchAll(/<script src="\/assets\/([^"]+)"><\/script>/g)){
  if(delayDeploymentScript && script[1]==='salesforce-deploy.js')continue;
  loadScript(script[1]);
 }
 return {elements,requests,loadDeployment:()=>loadScript('salesforce-deploy.js'),run:code=>vm.runInContext(code,context),trigger:(id,event)=>elements[id].listeners[event]({preventDefault(){}})};
}
const change=(element,value,event='change')=>{element.value=value;element.listeners[event]();};
(async()=>{
 const delayed=page('salesforce.html','?project=abc123',true);
 assert.equal(delayed.requests.length,0,'review must not fetch/render before deployment helpers load');
 delayed.loadDeployment();await delayed.run('reviewReady');
 assert.equal(delayed.elements.reviewEntities.children.length,1);
 const discovery=page('index.html');
 discovery.elements.file.files=[{name:'legacy.zip'}];
 await discovery.trigger('scanForm','submit');
 assert.equal(discovery.elements.businessRows.children[0].children[0].textContent,inventory.business_contracts[0].name,'source text must never become HTML');
 assert.equal(discovery.elements.terraformRows.children[0].children[0].textContent,'aws_instance.app');
 assert.equal(discovery.elements.salesforceLink.href,'/salesforce?project=abc123');
 assert.equal(discovery.elements.irNodes.children[0].children[0].textContent,'model_candidate');
 assert.equal(discovery.elements.irNodes.children[0].children[1].textContent,'<unsafe candidate>');
 assert.equal(discovery.elements.irNodes.children[0].children[2].textContent,'models.py:2');
 assert.equal(discovery.elements.irNodes.children[0].children[3].textContent,'ticket');
 assert.equal(discovery.run('repositoryIR.nodes[0].fields[0].source'),'Incident.ticket');
 await discovery.trigger('downloadIR','click');assert.equal(downloads,1);
 assert.ok(!discovery.elements.reviewEntities,'discovery page must not contain the Salesforce worksheet');
 assert.ok(discovery.requests.every(url=>!url.includes('/canonical/')),'scanning at / must not request Salesforce review');
 const restored=page('index.html','?project=abc123');await restored.run('discoveryReady');
 assert.equal(restored.elements.businessCount.textContent,1);
 assert.equal(restored.elements.irNodes.children[0].children[1].textContent,'<unsafe candidate>');
 assert.equal(restored.elements.salesforceLink.href,'/salesforce?project=abc123');
 const review=page('salesforce.html','?project=abc123');await review.run('reviewReady');
 const {elements,trigger,run}=review;
 assert.ok(!elements.businessRows,'review page must not duplicate discovery inventory');
 assert.equal(elements.backToDiscovery.href,'/?project=abc123');
 assert.equal(elements.exportMetadata.disabled,true);
 const section=elements.reviewEntities.children[0],entitySelect=section.children[1];
 const row=section.children[4].children[0].children[1].children[0];
 const target=row.children[1].children[0],fieldSelect=row.children[5].children[0];
 change(entitySelect,'approved');assert.equal(run('approvedFields()'),0);
 await trigger('saveReview','click');assert.equal(elements.exportMetadata.disabled,true,'entity approval alone must not enable export');
 change(fieldSelect,'approved');await trigger('saveReview','click');assert.equal(savedPlan.entities[0].fields[0].evidence,'models.py:2');assert.equal(elements.exportMetadata.disabled,false);
 await trigger('exportMetadata','click');assert.equal(downloads,2);
 change(target,'RenamedTicket','input');assert.equal(elements.exportMetadata.disabled,true);
 failSave=true;await trigger('saveReview','click');assert.equal(elements.reviewNotice.textContent,'Unverified evidence');assert.equal(elements.exportMetadata.disabled,true);
 failSave=false;let resolveSave;deferSave=new Promise(resolve=>resolveSave=resolve);
 const pending=trigger('saveReview','click');change(target,'ChangedDuringSave','input');resolveSave();await pending;
 assert.equal(elements.exportMetadata.disabled,true,'stale save must not enable export');deferSave=null;
 let resolveCandidate;deferCandidate=new Promise(resolve=>resolveCandidate=resolve);
 const stale=page('salesforce.html','?project=abc123');stale.run('projectId="another";revision++;reviewPlan=null;');resolveCandidate();await stale.run('reviewReady');assert.equal(stale.run('reviewPlan'),null);
 deferCandidate=null;const empty=page('salesforce.html');await empty.run('reviewReady');assert.equal(empty.requests.length,0);assert.match(empty.elements.reviewNotice.textContent,/Scan a repository/);

 permissionsEnabled=true;
 const actionable=page('salesforce.html','?project=abc123');await actionable.run('reviewReady');
 const group=actionable.elements.reviewEntities.children[0];
 const cells=group.children[4].children[0].children[1].children[0].children;
 change(cells[5].children[0],'approved');
 assert.equal(actionable.elements.saveAndValidate.disabled,true);
 assert.match(actionable.elements.reviewSummary.textContent,/Approve the parent entity/);
 change(group.children[1],'approved');
 assert.equal(actionable.elements.saveAndValidate.disabled,false);
 await actionable.trigger('saveAndValidate','click');
 assert.equal(actionable.elements.objectPermissions.children[0].children[4].textContent,'No');
 assert.equal(actionable.elements.validateSalesforce.disabled,false);
 assert.equal(actionable.elements.deploySalesforce.disabled,false);
 assert.equal(releaseCalls.at(-1).action,'validate');
 change(cells[1].children[0],'NewTicket','input');
 assert.equal(actionable.elements.deploySalesforce.disabled,true,'editing the review invalidates browser deployment');
 await actionable.trigger('saveReview','click');
 releaseFails=true;await actionable.trigger('validateSalesforce','click');
 assert.equal(actionable.elements.deploySalesforce.disabled,true,'a failed CLI job must not enable deploy');
 assert.match(actionable.elements.releaseLog.textContent,/failed/);
 releaseFails=false;await actionable.trigger('validateSalesforce','click');
 change(actionable.elements.frontendUrl,'https://mim.example/alexa','input');
 assert.equal(actionable.elements.deploySalesforce.disabled,true,'changing the frontend invalidates deployment');
 assert.equal(actionable.elements.saveAndValidate.disabled,true,'unsaved frontend must not reuse an earlier matrix');
 await actionable.trigger('saveFrontend','click');
 assert.equal(savedFrontendUrl,'https://mim.example/alexa');
 assert.equal(actionable.elements.previewFrontend.href,'https://mim.example/alexa');
 assert.equal(actionable.elements.deploySalesforce.disabled,true);
 await actionable.trigger('validateSalesforce','click');
 actionable.elements.assignPermissionSet.checked=true;
 await actionable.trigger('deploySalesforce','click');
 assert.equal(releaseCalls.at(-1).action,'deploy');
 assert.equal(releaseCalls.at(-1).org_alias,'hackfest-developer');
 assert.equal(releaseCalls.at(-1).assign_to_current_user,true);
 assert.equal(actionable.elements.deploySalesforce.disabled,true,'deployment consumes validation in the UI');
 assert.match(actionable.elements.releaseNotice.textContent,/Deployment succeeded/);
 actionable.run(`renderProcedures([{records:[{procedure_type:'MOP',procedure_id:'LAB-BFD',title:'<unsafe title>',service:'SYNTHETIC-NETWORK',source_file:'data/mops.json',reference:'/0',record:{implementation_steps:['Inspect state'],validation_steps:['Reobserve']}}]}])`);
 assert.match(actionable.elements.procedureSummary.textContent,/1 discovered procedures/);
 assert.equal(actionable.elements.procedureRows.children[0].children[2].textContent,'<unsafe title>','catalog titles must be plain text');
 assert.equal(actionable.elements.procedureRows.children[0].children[5].textContent,'data/mops.json#/0');
 assert.equal(actionable.elements.exportProcedures.disabled,false);
 actionable.run(`renderReview({...reviewPlan,entities:[{...reviewPlan.entities[0],concept:'DIP'}]},false)`);
 assert.match(actionable.elements.reviewEntities.children[0].children[0].textContent,/Procedure/);
 assert.equal(actionable.elements.reviewEntities.children[0].children[4].children[0].children[1].children[0].children[0].textContent,'ticket');

 console.log('Discovery, separate Salesforce review, permissions matrix, validation/deploy controls and race checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

