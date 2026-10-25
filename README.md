# LifeAfterCode DevOps

Discover **business contracts and Terraform inventory from legacy source code**,
then review source-backed business entities for Salesforce metadata export.

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

Open http://127.0.0.1:8000 and upload a repository ZIP. The `/` landing page leads with the **evidence-backed repository preview**:
Kind, Candidate, Evidence and Fields from the existing repository IR. Business
contract candidates and existing Terraform declarations remain below it. Follow the Salesforce
mappings link to `/salesforce` for the separate entity/field approval worksheet.
Returning to discovery reopens the same saved scan. No reconstruction workers are needed.

Business discovery currently uses Python declarations and JSON keys; it is
heuristic. Terraform discovery inventories HCL / `.tf.json` block declarations;
it does not evaluate attributes, expand modules or confirm live infrastructure.
No uploaded code, Terraform command or Salesforce deployment runs during scanning.

For Salesforce, approve both each entity and the fields to export, then save the
review. The `/salesforce` page displays the generated permissions matrix. Click
**Save & check hackfest-developer**, then **Deploy approved to hackfest-developer**.
The action toolbar stays beside the approval summary; it reports fields that
still need parent-entity approval.
Optionally tick assignment to the current CLI user. Browser deployment uses the
Salesforce CLI login on the computer running `python run.py` at localhost.

The ZIP/terminal path remains available as an alternative:

```powershell
# Check-only validation (default; no deployment).
.venv\Scripts\python.exe run.py salesforce --metadata-zip "$HOME\Downloads\lifeaftercode-salesforce-metadata.zip"

# Validate, then deploy the reviewed schema, app/tabs and scoped permissions.
.venv\Scripts\python.exe run.py salesforce --metadata-zip "$HOME\Downloads\lifeaftercode-salesforce-metadata.zip" --approve --assign-to-current-user
```

The default org is `hackfest-developer`. Salesforce CLI must already be installed
and authenticated on this computer. The runner reuses the existing deployment
playbook; no manual ZIP extraction or new orchestration service is required.
See [the Salesforce workflow](docs/SALESFORCE_PLAYBOOK.md) for details. Discovery does not deduplicate
existing Salesforce contracts or automatically create records.

Build the focused judge package with `python scripts/package_submission.py`.
The generated ZIP excludes Alexa, network simulation and reconstruction workers.
Optional reconstruction, Alexa and network experiments are retained only on
[`internal/development-reference`](https://github.com/grpo8172/LifeAfterCodeDevOps/tree/internal/development-reference).
The `main` branch is the focused competition entry.

Source baseline: ContractCyber `feat/alexa-conversational-simulation`,
commit `e18c198914e2480f0fd91c47b5196ec708197554`.

Validation: `python -m pytest -q`.

[Implementation map](docs/IMPLEMENTATION.md): reused modules, connected routes,
and the status of the previous browser deploy button.

To reuse the existing hosted Alexa/MIM frontend, configure its HTTPS URL in
**Hosted MIM frontend** on `/salesforce`, save it, and validate/deploy again. This
adds a **MIM Workspace** tab to the existing Lightning app. See
[frontend hosting and runtime boundaries](docs/MIM_WORKSPACE.md).

Live Salesforce incident review: open `/mim` locally. See [configuration and runtime boundary](docs/MIM_INCIDENTS.md). Reuses the retained DIP matcher; read-only, no simulated fallback or write-back.

Seeded network discovery and reviewed Salesforce upsert: [seed import workflow](docs/SEED_IMPORT.md). Reuses catalog identities, proposes missing fields, and keeps synthetic observations separate from templates.

Connect imported node observations and the Salesforce DIP catalog to MIM decisions: [network decision setup](docs/MIM_NETWORK_DECISIONS.md). Local CLI mode; fresh, linked synthetic evidence is required.


DIPs, MOPs, SOPs and runbooks now share a [Procedure discovery and review view](docs/PROCEDURES.md), including structured JSON catalogs on the Salesforce review page. Rescan older uploads after pulling this update.

The builder can [sync reviewed procedure records after schema deployment](docs/BUILDER_RECORD_SYNC.md), using an approved unique source ID and only approved fields. The builder stays outside Salesforce.
