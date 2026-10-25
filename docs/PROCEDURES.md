# Unified procedure discovery

DIPs, MOPs, SOPs and runbooks are presented as **Procedure**: source-backed definitions of implementation, validation and rollback steps that can inform remediation pipeline reconstruction. Their original terminology, IDs, scope, risk, provenance and payload remain intact. Definitions alone do not prove executable steps, correct ordering across procedures, approvals or successful outcomes.

The repository scanner reads structured catalogs named `dips.json`, `mops.json`, `sops.json`, `runbooks.json`, `procedures.json` and `synthetic_network_mops.json`. A record needs a source ID and a structured steps array; records without those are skipped with a coverage warning. Lists, single records and named catalog envelopes are supported. No uploaded code is run.

On `/salesforce`, **Discovered procedures** shows the records, source kinds, step counts and JSON pointers. **Download discovered procedure catalog** retains the original records. The shared Procedure entity appears in the existing schema approval worksheet, with actual JSON fields inferred from the catalogs. Repeated common fields are shown once per type; complete source records remain available above. Lists and nested fields use LongTextArea proposals so structured steps are not reduced to a 255-character field. Field approval remains bound to the saved source pointer and type.

The stored canonical key/API suffix remains `DIP` for compatibility with existing metadata naming; its display label is Procedure. No automatic object migration, data import, schema deployment or execution is performed. New repository ZIP bytes still have their own repository namespace under the existing naming policy; this change does not identify or merge previously deployed objects across different ZIP hashes.

After pulling/restarting, **rescan the MIM-with-MOPs ZIP**, then open that scan's Salesforce review link. Old scans cannot acquire JSON evidence that was not captured. Existing saved approvals are preserved; newly available entity candidates remain unapproved and require a new save. Schema approval is distinct from approving a procedure record or remediation action.

The synthetic seed importer remains a separate reviewed data-import path. This change connects catalogs to discovery and schema review; it does not claim to reconstruct executable pipelines automatically or replace the existing incident/evidence reader.
