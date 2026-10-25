# Run → scan → review → release

## Start the app

On Windows, from this checkout:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

`run.py` starts `app.main:app` at http://127.0.0.1:8000/. It uses the checkout's
`workspace/` for saved scans. Use `run.py serve --port 8001 --workspace PATH` to
change these. No Alexa, synthetic-network or reconstruction services start.

## Select the relevant Salesforce schema

1. Upload the legacy repository ZIP at `/`.
2. Inspect business-contract and Terraform evidence.
3. Follow **Review Salesforce mappings** to `/salesforce?project=…`.
4. Approve only the required business entities and fields, then save the review.
5. Inspect the proposed object/field permissions matrix below the saved review.
6. Click **Save & check hackfest-developer** in the toolbar above the fields.
   This saves the current review, loads the matrix and starts validation. Only a
   successful validation enables **Deploy approved to hackfest-developer**.
   The approval summary explains when selected fields still need parent-entity
   approval.
7. Optionally select permission-set assignment to the current CLI user, then
   deploy. Actual job status and CLI results appear on the page.

The browser bridge is enabled by `python run.py` on loopback hosts and uses the
CLI login on that same computer. It is disabled for externally bound hosts and
cannot use your laptop's Salesforce login from an AWS-hosted app. Editing the
review clears validation. Deployment validates again before writing. Browser
job status and validation receipts are process-local; restarting the app requires
fresh validation. The old field-only `/api/projects/{id}/deploy` stays blocked.

You can still download `lifeaftercode-salesforce-metadata.zip` for the terminal
workflow below.

The app verifies source evidence before export. Business-symbol matches and
Terraform inventory do not automatically become Salesforce objects. The ZIP
contains `canonical-review.json` and only approved object/field metadata.

## Validate and deploy on the authenticated workstation

The existing Salesforce CLI login for `hackfest-developer` is reused. No access
tokens are needed in project files. From the LifeAfterCode checkout:

```powershell
# Check-only: the default mode makes no metadata or permission changes.
.venv\Scripts\python.exe run.py salesforce --metadata-zip "$HOME\Downloads\lifeaftercode-salesforce-metadata.zip"
```

After reviewing validation results:

```powershell
# Validation must succeed again before deployment starts.
.venv\Scripts\python.exe run.py salesforce --metadata-zip "$HOME\Downloads\lifeaftercode-salesforce-metadata.zip" --approve --assign-to-current-user
```

Use `--org ALIAS` to select another explicitly authorized Developer org or sandbox.
`--assign-to-current-user` opts into assignment of the generated scoped permission
set. Omit it when permissions are managed separately; the inherited post-deploy
field checks still require the CLI user to have access to those fields.
`--app-label "LifeAfterCode MIM"` changes the Lightning app display label.

The runner reproduces metadata from the approved review and rejects mismatched
or extra ZIP contents. It calls the **existing** Salesforce deployment playbook
for check-only validation, schema/app/tab/permission deployment, and field
visibility checks. Salesforce API names and permission-set identities retain the
existing scheme rather than adding another application-specific naming system.

This deploys metadata, not records or a rebuilt legacy application. Existing
record migration, Salesforce identity matching and deduplication are not added
by this runner. Keep the same reviewed bundle when repeating a release; a newly
packaged source ZIP can change the repository namespace and needs review before
creating objects. Terraform evidence remains read-only source inventory.

The lower-level interface is still available:

```powershell
python scripts/salesforce_deploy_playbook.py --help
```

Live deployment requires the authenticated Salesforce CLI on your workstation;
o live org deployment was performed from the development environment.

## Windows temporary-folder cleanup

Salesforce CLI helper processes can briefly retain a handle to their temporary
project directory. Release-directory cleanup is best-effort so a Windows file
lock cannot replace the confirmed validation/deployment result. A locked folder
may remain in the Windows temp directory. Actual Salesforce failures still stop
the release, and deployments still run their post-deployment field checks.
