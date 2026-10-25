# Implementation map

Use existing modules and routes when extending the workflow. Status describes
LifeAfterCode `main`, rather than assuming a visible button proves integration.

| Capability | Existing implementation | Current status |
| --- | --- | --- |
| Repository ZIP scan | `app/main.py`: `POST /api/analyze`; `discovery.py`, `scanner.py`, `intermediate_representation.py` | Reused; one scan produces the source IR and inventories. |
| Kind / Candidate / Evidence / Fields | `app/assets/discovery.js`: `renderRepositoryPreview` | Restored at `/`; short field labels are display-only. |
| Business contract candidates | `app/business_discovery.py` | Reused; heuristic source symbols, not automatic approvals. |
| Terraform source declarations | `app/terraform_inventory.py` | Added for `.tf` / `.tf.json`; distinct from the old synthetic-state reader. |
| Saved discovery and IR | `GET /api/projects/{id}/discovery` | Reopens the same stored scan; no re-scan needed. |
| Salesforce review UI | `/salesforce`; `app/assets/salesforce-review.js` | Saves reviewed entities and fields against source evidence. |
| Source-evidence approval gate | `app/canonical_project_api.py`, `app/canonical_evidence.py` | Reused; entity and field approvals are both required. |
| Reviewed metadata export | `GET /api/projects/{id}/canonical/metadata.zip`; `reviewed_metadata.py`, `salesforce.py` | Reused; outputs approved schema and its review JSON. |
| Salesforce validation / deployment / scoped permissions / tabs | `scripts/salesforce_deploy_playbook.py` | Existing CLI implementation; requires an authenticated Salesforce workstation. |
| Simplified startup / release command | `run.py` | Thin entry point over the existing app, exporter and playbook; validation precedes deployment. |
| Browser permissions and deploy controls | `app/salesforce_browser.py`, `app/assets/salesforce-deploy.js`; project-scoped `/salesforce/permissions`, `/validate`, `/deploy`, `/jobs/{id}` | Connected to the canonical saved review and existing `run.py`/playbook. Local workstation only; target is `hackfest-developer`. Validation is bound to the review digest. |
| Retired field-only deploy button | Old ContractCyber `app/index.html`: `deploy()` → `POST /api/projects/{id}/deploy` | Its old backend returned 403 in the copied source; that unverified field-only endpoint remains blocked. |
| Mapping-record sync | Old ContractCyber `app/salesforce_client.py`: `sync_approved_mappings` | Retained on `internal/development-reference`; not connected to the current canonical release path. |
| Existing hosted MIM frontend | `scripts/salesforce_workspace/`, `generate_frontend_workspace`; project-scoped `/salesforce/frontend` | Generates a scoped LWC iframe/tab and frame-only Trusted URL. Existing frontend and request handlers stay on the configured company host; no Salesforce session is forwarded. |
| Record migration and existing-contract identity matching | No integrated current release path | Not implemented by the metadata runner; do not claim records were loaded or deduplicated. |
| Reconstruction / Alexa / network demos | `internal/development-reference` | Preserved separately; excluded from the focused runtime and submission. |

## Browser deployment reuse

The browser controls reuse the canonical saved review, its evidence validation,
existing metadata exporter, permission generator and deployment playbook. The
retired client-authored field-only endpoint is not reactivated.
Actual org validation/deployment and record sync remain separate verification
steps; offline tests do not establish that either ran against a live org.

## Salesforce incident decision slice

`app/mim_incidents.py` uses the existing local CLI authorization boundary and retained `mim_dip_recommendation.py` matcher. `/mim` reads configured incident fields, rereads a selected record, and reports source evidence plus an advisory plan. Regression tests cover CLI-only reads, target alias, field allowlisting, origin gates, errors, missing records, injection and abstention. The hosted `/alexa` runtime remains separate. A `/mim` frontend URL opts into a generated scoped Apex USER_MODE reader and an exact-origin selected-record bridge. No hosted OAuth adapter, Salesforce catalog reader, approval write-back or execution is claimed. See MIM_INCIDENTS.md.

## Seeded network data import

The repository inventory discovers supported seed JSON without executing generators. `app/seeded_network_import.py` creates stable lab/node/observation identities and reuses existing catalog keys. `scripts/seeded_network_sf.py` separates offline planning, live schema preflight/missing-field proposals, and explicit digest-approved bulk upsert to hackfest-developer. No live org writes were performed during development; related network evidence is not yet consumed by the MIM recommendation reader. See SEED_IMPORT.md.

## Salesforce network decision context

`app/mim_network_context.py` connects an explicitly mapped incident node key to imported observation records and approved Salesforce catalog contracts. The local reader verifies source keys/digests, lab relationships, freshness, latest-sample consistency and service scope, then reuses structured boolean signal matching. No local catalog fallback, baseline change or execution. Hosted incident-only snapshots reject this mode until their related-evidence transport is implemented. See MIM_NETWORK_DECISIONS.md.


## Unified procedure discovery and Salesforce review

`procedure_catalog.py` parses supported structured catalogs into one procedure concept while retaining source kind, original record and JSON pointer. The IR carries real catalog field evidence into canonical schema review. The Salesforce page lists discovered procedure data, offers an evidence export and labels the shared DIP-compatible entity as Procedure. Arrays/nested data use reviewed LongTextArea metadata. No data import or pipeline execution is implicit; old saved scans require rescanning.

## Approved builder data sync

Procedure field review now includes an explicit unique external-ID flag. The browser previews a server-derived record plan and can opt into syncing only approved source fields after confirmed schema deployment. The existing bulk upsert/preflight helper handles writes; partial success retains the schema outcome. Runtime remains local/CLI-authenticated until an AWS service adapter is configured. See BUILDER_RECORD_SYNC.md.
