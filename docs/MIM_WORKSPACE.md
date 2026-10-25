# Existing MIM frontend inside Salesforce

This slice adds a **MIM Workspace** Lightning tab that embeds the existing hosted
frontend, including its original service requests and evidence/voice UI. The
frontend and Python runtime continue on the company-controlled host. No duplicate
MIM engine or Alexa workflow is built in Salesforce.

## Browser deployment

1. Start the updated checkout with `python run.py` on the authenticated workstation.
2. Reopen the existing source project and its Salesforce review.
3. In **Hosted MIM frontend**, enter the full HTTPS frontend URL (the existing
   Alexa demo uses its `/alexa` path), then **Save frontend URL**.
4. Use **Open hosted frontend / sign in** to confirm the app and its login work.
5. Inspect the permissions matrix and workspace URL, then **Save & check**.
6. Deploy after successful validation. Assign the scoped permission set if needed.
7. Open LifeAfterCode in Salesforce and select **MIM Workspace**. Salesforce may
   initially restore the last object tab you used.

The existing object, field and app identities are preserved. The release adds an
LWC wrapper, its tab/visibility and a frame-only Trusted URL for the exact host.
Changing the URL invalidates prior validation. A blank URL keeps record tabs only;
this does not delete previously deployed workspace metadata or Trusted URLs.

## Existing terminal deployment

The same generator and playbook are used by both interfaces:

```powershell
.venv\Scripts\python.exe run.py salesforce --metadata-zip "$HOME\Downloads\lifeaftercode-salesforce-metadata.zip" --frontend-url "https://your-company-host.example/alexa"
```

Add `--approve` after reviewing validation; optionally add
`--assign-to-current-user`. The download is the reviewed schema ZIP. The frontend
URL is separate, explicitly selected release configuration.

## Runtime boundary

The embedded page stays on its original origin, so its relative API/MCP requests
continue to reach the same runtime. This tab does not pass Salesforce sessions,
passwords or tokens to that host, write incident records, or connect native
Salesforce approval to simulated recovery. Those adapters are separate work.

The host must permit framing by the exact Salesforce Lightning origin. Salesforce
Trusted URLs cannot override the host's X-Frame-Options or CSP frame-ancestors.
Keep the runtime's authentication. If its login cannot run inside a frame, use the
open-hosted-workspace link; company SSO/frame-compatible login can be configured
separately. Browser microphone/speech availability depends on browser and host
policy; typed requests remain the existing frontend's fallback.

No AWS configuration or existing submission deployment is changed by this release.
The Salesforce check-only deployment compiles/validates metadata; loading the
hosted page and its authenticated requests must then be checked in the live org.
