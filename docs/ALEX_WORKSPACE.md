# Builder publishes; Alexa reads Salesforce

Both sites run in the same FastAPI process: `/` is the engineer/vendor builder, `/alexa` is the customer incident/procedure workspace. `/alex` remains an alias. Salesforce stores the shared data; neither frontend needs to be embedded there.

## Publish from the builder

A successful **deploy with procedure record sync selected** now freezes the deployed mappings and source IDs into a durable publication. `/alexa` opens the latest successfully published workspace without asking the customer for a builder project ID. The builder also links directly to `/alexa?project=PROJECT_ID` for a specific publication.

For the 206 records synced before this feature, open their saved review, save it to load the record preview, then click **Activate previously synced records for Alexa**. The server verifies that the approved fields are queryable and all expected IDs exist in the target Salesforce object before publishing. This is read-back verification, not another import. Missing records or stale review digests block activation.

Editing or saving builder drafts does not change published mappings. Schema-only deployment and failed sync do not publish a new workspace. Publication retains the exact deployed review even if another draft is saved during a running bulk job. Later successful sync republishes the new scope. Salesforce bulk writes are not transactional: a failed job can still partially change existing live values, even while the prior publication remains active. Inspect partial failures before retrying.

Publications and the active pointer persist in the configured `MAPPER_WORKSPACE` directory. Preserve this directory when moving hosts. The unscoped `/alexa` route selects the most recently published project for this single demo installation; explicit project links remain available. This is not tenant routing or role-based access control.

## Customer queries

Every request reads **current Salesforce values**, selecting only the published object and approved fields and limiting procedure results to the published source IDs. There is no source-ZIP, private-catalog or BFD-simulation fallback. Record IDs, modification times, publication digest and retrieval evidence are displayed. Draft field changes cannot leak through this query path.

Ask **Find BFD procedures** or **Find cyber procedures**. Only synced fields can contribute to the result: an ID-only sync enables ID lookup, while titles, implementation, rollback and validation content require approving and syncing those fields too. Multiple matches remain review candidates rather than an automatic remediation choice.

If the deployed review also approved an Incident entity and its fields, the publication includes that object's mapping. Alexa lists recent Salesforce incidents. Selecting one rereads its current service/summary/description/impact fields and searches procedures using that content rather than the typed topic. Missing mappings, empty symptoms or unreadable records are explained; incidents are not fabricated. The builder currently imports procedure definitions, not incident instances inferred from Python class declarations, so incident records must exist in Salesforce separately.

This is a real Salesforce incident-to-procedure retrieval path, not the original voice/MCP diagnostic agent. It does not collect node diagnostics, establish root cause, approve actions or execute remediation. Node-specific requests ask for clarification rather than returning hardcoded simulated BFD output.

## Runtime boundary

The implementation uses the existing local Salesforce CLI login for **hackfest-developer**. Pull/restart, activate an existing completed sync or deploy-and-sync, then open `/alexa`. Both interfaces remain on one server. The original AWS Alexa competition deployment is untouched.

AWS deployment still needs authenticated hosted Salesforce access and customer/vendor authorization before exposing these endpoints. The local-only boundary is deliberately retained; it is not made public by adding these routes. No live Salesforce or AWS changes were performed during development.
