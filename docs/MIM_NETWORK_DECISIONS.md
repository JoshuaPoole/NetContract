# Salesforce evidence → MIM decision

This connection extends the local `/mim` incident reader. It reads the incident, its related imported network observations, and Salesforce's approved synthetic DIP catalog through the CLI login for **hackfest-developer**. No company-hosted Salesforce credentials, record writes, approval changes or commands are introduced.

## Configure the connection

Use the existing seed import workflow first. The default evidence and catalog field names below match that importer. Add/review an incident Text field for the imported node's stable source key; map its exact API name as `node_key`. Do not guess node relationships from prose or incident titles.

Your private file referenced by `LIFEAFTERCODE_MIM_CONFIG` can use this mode instead of the local `catalog` section:

```json
{
  "incident": {
    "object": "R7ac51ef9_Incident__c",
    "service": "Service__c",
    "short_description": "Summary__c",
    "node_key": "NodeKey__c"
  },
  "network_context": {
    "lab_namespace": "hackfest-network-lab",
    "max_age_seconds": 900,
    "evidence_object": "MIM_NetworkEvidence__c",
    "catalog_object": "MIM_DIP__c"
  }
}
```

The service and summary field names are illustrative: use your reviewed deployed names. `network_context` makes this mode explicit; there is no fallback to a private or synthetic-in-memory catalog. Existing private-catalog mode remains available when this section is absent. Custom evidence/catalog field mappings can be supplied using the explicit settings in `NetworkContext`.

## One incident demo

1. Export and import a fresh actual simulator observation using the seed workflow and a stable lab namespace. An old saved timestamp will correctly be rejected as stale; do not replace its timestamp with the current time merely to bypass that check.
2. In Salesforce, review the imported BFD procedure, then set its `CatalogReviewStatus__c` to `approved` if appropriate. Seed import deliberately starts/resets procedures at `needs_review`.
3. Populate an incident with service `SYNTHETIC-NETWORK`, a summary, and the imported node record's **SourceKey__c** in the configured incident node-key field. This must be the 64-character stable source key, not the Salesforce record ID or `NODE-00001` label.
4. Start/restart `python run.py` with the private configuration. Open `http://127.0.0.1:8000/mim`, read incidents, select that incident and review the recommendation.
5. A fresh attention observation with `sample.alarm_observations["bfd.session_down"]` exactly `true`, and one service-matching approved BFD contract, should produce a review-only recommendation. The output identifies the incident, observation record, catalog records, digests and evidence age.

For later observation cycles, import an export directory containing only `network-export.json` under the same namespace. Reimporting a plan that includes procedures resets their catalog review state; do not automatically reapprove them. Node and observation imports do not change a reviewed baseline or delete history.

## Decision rules

The reader reuses the original `network_mop_catalog.discover_contracts` structured signal-matching semantics in a small dependency-free function. It does not use natural-language similarity to override missing telemetry. It considers the latest observation by its timezone-aware `observed_at`, not Salesforce LastModifiedDate. Default freshness is 15 minutes (configurable up to 24 hours); observations over 30 seconds in the future are rejected. Conflicting latest observations, invalid source keys, lab mismatches, digest changes or malformed evidence stop the decision.

Only observation rows are queried. Command templates are never treated as observed command results. A newer healthy/unknown sample prevents an older alarm from being reused. Only explicit boolean `true` matches; strings, numeric values, false and unknown do not. The approved catalog must have consistent versioned keys/digests, synthetic provenance, disabled execution and supported fresh boolean triggers. Matching is service scoped; multiple matching contracts yield ambiguity rather than selecting one.

Limits are 200 related observation rows per node and 1,000 approved catalog rows. Over-limit or incomplete Salesforce query responses fail rather than silently choosing from partial data. Archive/review history before increasing scale. Current queries are sequential snapshots, not a transaction or a guarantee that data cannot change after the result. Each new review rereads the incident and context.

## Current runtime boundary

This mode works through the **local Salesforce CLI reader**. The existing hosted iframe bridge only transports an incident snapshot; it has no authenticated related-evidence query path yet. Selecting network-context mode in that hosted snapshot endpoint returns a clear error instead of silently using the old private catalog. Extending the hosted Apex/service transport is still required for this mode to run inside the company-hosted iframe. The original AWS `/alexa` submission is unchanged.

All output remains advisory and synthetic, with `authorization_evidence_trusted=false`, no automatic baseline updates, no Salesforce writes and no execution. The observation says what the lab reported; it is not proof of real network state.
