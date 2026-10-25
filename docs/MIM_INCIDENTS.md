# Live Salesforce incident review

Open `http://127.0.0.1:8000/mim` after starting `python run.py` on the computer authenticated to **hackfest-developer**. This is the first read-only connector, using the same local Salesforce CLI boundary as metadata deployment. It does not change the already hosted Alexa submission, populate Salesforce, migrate records, execute DIPs or write approvals.

The embedded `/alexa` submission still uses its original simulation. This new `/mim` route reads real Salesforce incident records locally. Do not point the Salesforce iframe at a localhost URL: Salesforce requires an HTTPS company-hosted frontend, and this local CLI connector deliberately refuses remote callers. The hosted path below uses Salesforce Apex under the signed-in Salesforce user instead of the local CLI.

## Private configuration

Create a JSON file outside the repository. Set the field API names from Salesforce Object Manager; do not copy these illustrative field names unless they exist. A deployment with only `payload_key`/`payload_path` cannot supply incident symptoms. Add/import incident records with service and descriptive text first. No additional schema is deployed by this reader.

```json
{
  "incident": {
    "object": "R7ac51ef9_Incident__c",
    "service": "Service__c",
    "short_description": "Summary__c",
    "description": "Description__c",
    "customer_impact": "CustomerImpact__c"
  },
  "catalog": {
    "source_evidence": ["YOUR_REPOSITORY_COMMIT:path/to/reviewed_dip.py:12"],
    "dips": [{
      "dip_id": "YOUR_REVIEWED_DIP_ID",
      "title": "YOUR_REVIEWED_TITLE",
      "category": "YOUR_REVIEWED_CATEGORY",
      "service": "YOUR_SERVICE",
      "review_status": "approved",
      "implementation_steps": ["YOUR_REVIEWED_STEP"],
      "validation_steps": ["YOUR_REVIEWED_VALIDATION"],
      "approval_groups": ["YOUR_REVIEWERS"]
    }]
  }
}
```

`description` and `customer_impact` are optional. Catalog entries must be explicitly approved. Reuse/export the existing reviewed source DIP catalog rather than inventing remediation steps. The current connector reads incidents from Salesforce; it reads the reviewed catalog from this private configuration, not `MIM_DIP__c` yet.

PowerShell:

```powershell
$env:LIFEAFTERCODE_MIM_CONFIG = 'C:\private\mim-runtime.json'
.\.venv\Scripts\python.exe run.py
```

Click **Read Salesforce incidents**, select a record, then **Review recommendation**. The app reads up to 50 recently modified records; selecting a record rereads its current values before matching. Salesforce enforces the CLI user's existing read access. Query failures remain errors; there is no synthetic fallback.

The existing `catalog_terms_v1` matcher from the development reference provides service-scoped term matching, evidence scores and abstention on weak or tied matches. Scores are not probabilities or an LLM inference. The result includes the object, record ID, LastModifiedDate, field mapping, observation time, record digest, catalog evidence and original matcher digest. An advisory plan is not an authorization. Every result requires human review; there is no command execution or approval/write-back endpoint.

No incident values, CLI credentials or query output are written to disk. Only configured decision fields are read; the list exposes ID, summary, service and modification date. Keep the browser and company machine under normal access controls, since incident text is displayed there.

## Hosted Salesforce workspace

Host this checkout's FastAPI runtime behind your existing company HTTPS authentication. Set `LIFEAFTERCODE_MIM_CONFIG` there too, using the reviewed incident mapping and catalog. Set `LIFEAFTERCODE_SF_PARENT_ORIGINS` to the exact Salesforce Lightning origin visible in your browser, for example `https://YOUR_ORG.lightning.force.com` (no trailing slash). Comma-separated exact origins are supported; wildcards are rejected. This is an explicit company deployment setting, not a client-supplied origin.

In the local `/salesforce` release page, set the frontend URL to `https://YOUR_COMPANY_HOST/mim`, save, validate and deploy again. The `/mim` path opts into generating the scoped Apex reader; `/alexa` keeps the existing wrapper behavior. Grant the generated permission set to the intended Salesforce user through the existing deployment control. The company server does not need Salesforce CLI or Salesforce tokens for this path.

Inside Salesforce: choose the reviewed incident object → **Read recent records** → select a record → **Send selected record for recommendation**. The list contains only record ID and Name. Sending rereads that one record and transfers the fields in the reviewed deployment scope to the exact configured frontend origin. Use a scope containing only fields the company permits this service to process. A selected record's missing decision fields produce an actionable error, not fabricated input.

The generated Apex class has `with sharing` and executes queries with `AccessLevel.USER_MODE`; the class's object and field allowlist is generated from approved metadata, not accepted from browser input. There is no DML. The LWC sends no Salesforce session or access token. The receiver checks the exact configured parent origin and source window. The backend only computes advisory output from that browser snapshot; it does not trust it as authorization evidence or claim to have independently verified its Salesforce origin. Its evidence labels it `salesforce_browser_snapshot`, with no asserted org alias. The local CLI path is separately labelled `local_cli_read`.

The hosted page and snapshot endpoint must remain behind company authentication. Parent-origin filtering is a browser transport check, not authentication for the server. No changes to the existing AWS Alexa submission are made automatically. Deploy this version to the company's chosen service before changing the Salesforce iframe URL. The existing HTTP authentication/frame restrictions still apply.

The Apex source and its generated tests must be compiled and validated in your org using **Save & check** before deployment. Local tests verify generated scope/security properties; they cannot substitute for org compilation. The receiver is a minimal evidence review page; porting these controls into the original richer Alexa dashboard can follow without replacing the matching/connector logic.
