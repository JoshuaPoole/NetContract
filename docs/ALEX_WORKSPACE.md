# Builder publishes; Alexa reads Salesforce

Both sites run in the same FastAPI process: `/` is the engineer/vendor builder, `/alexa` is the customer incident/procedure workspace. `/alex` remains an alias. Salesforce stores the shared data; neither frontend needs to be embedded there.

## Publish from the builder

A successful **deploy with procedure record sync selected** now freezes the deployed mappings and source IDs into a durable publication. `/alexa` opens the latest successfully published workspace without asking the customer for a builder project ID. The builder also links directly to `/alexa?project=PROJECT_ID` for a specific publication.

For the 206 records synced before this feature, open their saved review, save it to load the record preview, then click **Activate previously synced records for Alexa**. The server verifies that the approved fields are queryable and all expected IDs exist in the target Salesforce object before publishing. This is read-back verification, not another import. Missing records or stale review digests block activation.

Editing or saving builder drafts does not change published mappings. Schema-only deployment and failed sync do not publish a new workspace. Publication retains the exact deployed review even if another draft is saved during a running bulk job. Later successful sync republishes the new scope. Salesforce bulk writes are not transactional: a failed job can still partially change existing live values, even while the prior publication remains active. Inspect partial failures before retrying.

Publications and the active pointer persist in the configured `MAPPER_WORKSPACE` directory. Preserve this directory when moving hosts. The unscoped `/alexa` route selects the most recently published project for this single demo installation; explicit project links remain available. This is not tenant routing or role-based access control.

## Customer queries

Every request reads **current Salesforce values**, selecting only the published object and approved fields and limiting procedure results to the published source IDs. There is no source-ZIP or private-catalog fallback for procedure records. Explicit node requests can use the clearly labelled synthetic diagnostic path below; they still require published Salesforce steps for intervention review. Record IDs, modification times, publication digest and retrieval evidence are displayed. Draft field changes cannot leak through this query path.

Describe the reported symptoms, for example **application server exploitation**, or request a node investigation below. Generic requests such as “investigate cyber incident” ask for symptoms rather than returning the entire catalog. Specific title matches take priority over incidental words in procedure bodies. Only synced fields can contribute to the result: an ID-only sync enables ID lookup, while titles, implementation, rollback and validation content require approving and syncing those fields too. Multiple matches remain review candidates rather than an automatic remediation choice.

If the deployed review also approved an Incident entity and its fields, the publication includes that object's mapping. Alexa lists recent Salesforce incidents. Selecting one rereads its current service/summary/description/impact fields and searches procedures using that content rather than the typed symptoms. Missing mappings, empty symptoms or unreadable records are explained; incidents are not fabricated. The builder currently imports procedure definitions, not incident instances inferred from Python class declarations, so incident records must exist in Salesforce separately.

This is a Salesforce retrieval path with an explicit, bounded lab adapter, not the original voice/MCP agent or an open-ended command generator. It does not establish real root cause or execute remediation.

## Synthetic node and cyber happy paths

Pull, restart the local app and refresh `/alexa`. Publish/sync the procedure identity, `title` and `implementation_steps` from the builder first. BFD requires `LAB-MOP-BFD`; cyber scenarios require the relevant `DIP-CYBER-00N` record. These are read from Salesforce on each investigation and again before approval/confirmation. Missing, duplicate, changed or unpublished records block intervention review.

| Request | Explicit lab scenario | Salesforce procedure |
| --- | --- | --- |
| List BFD alarms on node 3 in UAT | BFD down; original committed command fixtures and parsers | LAB-MOP-BFD |
| Investigate application exploitation on node 4 in UAT | Synthetic application exploitation alert | DIP-CYBER-001 |
| Investigate endpoint compromise on node 5 in UAT | Synthetic endpoint alert | DIP-CYBER-002 |
| Investigate exfiltration on node 6 in UAT | Synthetic exfiltration alert | DIP-CYBER-003 |

The new `data/node_lab.json` is an explicit eight-node **demo inventory**, not scraped live infrastructure. All targets use documentation-only IPs in `192.0.2.0/24`, UAT and a localhost controller. “Login” is an Ansible-style trace with unused placeholder credentials. No Ansible process, shell, SSH, socket, password authentication or real host connection is performed. Node 1 and 3 start BFD down; other BFD fixtures start healthy. Cyber scenarios are independently configured on nodes 4–6. Spoken “node three” is accepted. Unknown nodes, mismatched environments, conflicting symptoms and multiple targets ask for clarification without a fallback.

Prechecks display command output and alarms. BFD uses the existing fixture renderer/parser; cyber uses explicit synthetic alert fixtures. The exact node-to-procedure bindings are configured demo rules, not inferred diagnoses. Cyber steps are interpreted by bounded leading-verb adapters into `ansible.builtin.command` **previews**: inspection, evidence preservation, isolation, service inspection, repair, placeholder credential rotation and monitoring. Source prose never becomes a shell command. `netcontract-lab` is a fictional command namespace, not an installed executable. Preview adapters do not fully implement nuanced prose such as patch selection or credential rotation. Unknown steps remain manual and block the simulation review.

Inspect the source steps and preview, then choose **Review simulated intervention**, followed by **Confirm simulated intervention**. Voice equivalents are “approve” and “confirm simulated intervention”. The confirmation is one-use and expires after 90 seconds; investigations expire after five minutes. Evidence, publication, Salesforce modification/content and node state are checked again. Confirmation logs synthetic task results for cyber, injects a healthy in-memory fixture state and reruns postchecks. BFD recovery is also a healthy-state injection, not implementation of its advisory steps. These results demonstrate the review loop only. No recovery is written back to Salesforce. Restart resets demo state.

When approved and synced, `target_environment_order` is read from Salesforce and must include the node environment. Without that field, the explicit lab inventory supplies the environment and the UI says so. Repository environment references are review evidence, not login authority; this version does not discover credentials or connect to arbitrary scraped hosts. A real connector would need an approved inventory mapping and an authorised credential provider. Imported incidents currently use retrieval only; they are not automatically converted into node investigations.

## Runtime boundary

The implementation uses the existing local Salesforce CLI login for **hackfest-developer**. Pull/restart, activate an existing completed sync or deploy-and-sync, then open `/alexa`. Both interfaces remain on one server. The original AWS Alexa competition deployment is untouched.

AWS deployment still needs authenticated hosted Salesforce access and customer/vendor authorization before exposing these endpoints. The local-only boundary is deliberately retained; it is not made public by adding these routes. No live Salesforce or AWS changes were performed during development.

## Voice and evidence presentation

The customer page includes a persistent conversation transcript, optional browser speech input and reply read-out, readable implementation/validation/rollback steps, always-visible session events, source JSON and an on-demand session evidence download. Microphone use starts only from the Speak request button and requires localhost or HTTPS plus browser permission. Speech recognition/read-out availability depends on the browser and can use its external speech services; typed input remains available.

Session events show actual connection/query activity. Ordinary retrieval explicitly indicates that no node commands were run. Node investigations show separate prechecks, task previews, simulated task results and postchecks; every trace is labelled simulated. “Show logs” opens the pinned evidence without starting a new lookup. Procedure definitions remain distinct from diagnostic output. Session history remains in browser memory until the user downloads it; it is not persisted to Salesforce.
