# Seeded network data → reviewed Salesforce import

The repository scan now reports supported JSON seed records alongside contracts and Terraform. It never runs seed Python code, Terraform or device commands. Supported filenames are `synthetic_network_mops.json`, `network_command_fixtures.json` and an explicit `network-export.json`. Discovery is static; generated nodes require an export of the running lab.

The default targets reuse **MIM_DIP__c** and its existing versioned **CatalogKey__c** identity. Other evidence is proposed for **MIM_NetworkEvidence__c**, with **SourceKey__c** as a unique external ID. Supply a mapping JSON with the same structure as `DEFAULT_MAPPING` in `app/seeded_network_import.py` to reuse a different existing evidence object. No fuzzy name matching, automatic object duplication or automatic schema deployment occurs.

## Run on your Salesforce-authenticated computer

From the LifeAfterCode checkout, using a directory containing the original repository seeds and any runtime export:

```powershell
.\.venv\Scripts\python.exe -m scripts.seeded_network_sf plan --source C:\repos\ContractCyber --namespace hackfest-network-lab --out C:\private\seed-plan.json
.\.venv\Scripts\python.exe -m scripts.seeded_network_sf check --plan C:\private\seed-plan.json --out C:\private\seed-schema
```

`plan` reads local files only. Keep the lab namespace stable across exports. The browser scan uses a clearly provisional namespace; the CLI plan supplies the real one. Plans contain seed data and should remain outside the Git repository.

`check` reads the current object descriptions from **hackfest-developer**. It reports reusable fields, incompatible types/lengths/permissions and missing fields, exporting **only missing field metadata**. Describe/authentication failures are errors, never assumed to mean an object is absent. It also blocks non-unique/non-external keys and unmapped required fields.

If you have independently confirmed that the evidence object does not exist, explicitly propose it:

```powershell
.\.venv\Scripts\python.exe -m scripts.seeded_network_sf check --plan C:\private\seed-plan.json --out C:\private\seed-schema-new --propose-new-object MIM_NetworkEvidence__c
```

This writes a new private object proposal with an AutoNumber Name. Do not use the new-object option for existing objects. Review `schema-review.json` and the generated metadata. Resolve blockers by changing the mapping or reviewing schema changes; existing fields are never silently resized or retyped. An external-ID field with existing duplicates needs a separate cleanup/review.

When approved, validate then deploy the proposed metadata from its generated project directory:

```powershell
cd C:\private\seed-schema-new
sf.cmd project deploy start --source-dir force-app --target-org hackfest-developer --dry-run --wait 15
# Only after reviewing successful validation:
sf.cmd project deploy start --source-dir force-app --target-org hackfest-developer --wait 15
```

Grant the intended import user the necessary object/field access through the reviewed permissions process. This importer does not assign permissions. Return to the LifeAfterCode checkout and upsert the exact reviewed plan:

```powershell
.\.venv\Scripts\python.exe -m scripts.seeded_network_sf apply --plan C:\private\seed-plan.json --approve-digest THE_REVIEW_DIGEST_PRINTED_BY_PLAN
```

`apply` validates the plan digest and target alias, preflights every target object again before writes, and uses Bulk API upsert with stable unique external IDs. It requires confirmed completion, zero failed records and the expected processed count. Partial jobs are errors; printed job IDs must be retained for inspection. Bulk operations across objects are not transactional. Retry the same reviewed plan after resolving failures; do not change keys or assume success. There is no deletion or baseline update.

## Runtime export shape

Export actual lab snapshots from the existing simulator; do not synthesize timestamps in the importer. Save them under the supported filename:

```json
{
  "simulation_only": true,
  "nodes": [
    {
      "device_id": "NODE-00001",
      "management_ip": "10.64.0.1",
      "peer_id": "NODE-00002",
      "site": "LAB-SITE-001",
      "role": "router",
      "simulation_only": true,
      "observed_at": "2026-10-25T08:00:00Z",
      "cycle": 1,
      "episode": 1,
      "status": "attention",
      "sample": {"bfd_state": "down"}
    }
  ]
}
```

The sample illustrates format, not a newly verified observation. Existing simulator `detail(node)["latest"]` provides the complete row, including `sample`, `checks` and observation time. A node row without `sample` imports inventory only. The importer intentionally does not read summary counts as detailed observations, run the original simulator or claim 5,000 nodes were found from a generator declaration.

## Evidence and feedback boundaries

Nodes keep stable lab-scoped keys. Observations have timestamp/content identities and retain history; their `NodeKey__c` links to the node key. This is an explicit source-key relationship, not a Salesforce Lookup yet. Command fixtures retain variants and placeholders and are labelled templates, never fresh node observations. All records retain synthetic provenance. DIP upserts preserve the original catalog key, include source contract JSON and reset catalog review status to `needs_review`; import is not procedure approval. Source commit evidence and any incident/Lookup mapping still require review.

This delivers discovery, schema comparison/proposals and an explicit data import path. The current MIM recommendation reader still uses its configured incident plus private catalog. Querying these new related evidence records and Salesforce's DIP catalog into the decision context is the next integration step; importing records alone does not complete that feedback loop. No AWS deployment or live Salesforce import was performed by these code changes.
