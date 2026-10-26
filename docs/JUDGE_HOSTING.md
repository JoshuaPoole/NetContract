# Judge access on EC2

The HTTPS judge login grants the shared demo operator role: upload and review source, read procedure previews, validate, deploy and sync approved metadata/records to `hackfest-developer`, and use `/alexa`. This is a single trusted judge workspace, not per-user tenancy or enterprise RBAC. Existing source evidence, review digests, field approvals, record identity checks and validation-before-deploy gates remain mandatory. No procedure execution on real devices is enabled.

Caddy protects the public site with Basic authentication. The app independently verifies the same username/password using a private PBKDF2 verifier file, and accepts the configured HTTPS origin only. Do not trust a caller-supplied username, client IP or forwarding header as authorization. Browser mutations require the exact Origin; Salesforce action endpoints also require their existing custom browser header. Static assets, uploads, review writes and reads are all behind app authentication when judge mode is enabled. Successful responses are not cached. No Salesforce tokens or passwords are delivered to the browser.

## One-time setup on the new EC2 instance

Use the existing Caddy configuration, with `basic_auth` and `reverse_proxy 127.0.0.1:8000`. Caddy forwards the Authorization and Host headers and supplies HTTPS proxy information. Never expose port 8000 publicly. `run.py` binds loopback by default and explicitly trusts proxy headers only from loopback, not arbitrary remote callers.

```bash
cd ~/NetContract
git pull --ff-only
.venv/bin/python -m scripts.configure_judge_access --origin https://3-25-74-9.sslip.io
```

Enter **the same password already configured in Caddy**, twice. It is not echoed, passed as a command argument or stored in plaintext. Username defaults to `judges`, matching the Caddyfile. Only a salted verifier is written, mode 0600, to `/home/ec2-user/.config/netcontract/judge-access.json`. A different Caddy username must also be supplied with `--username`.

Enable the verifier explicitly in the existing systemd service:

```bash
sudo mkdir -p /etc/systemd/system/netcontract.service.d
sudo tee /etc/systemd/system/netcontract.service.d/judge-access.conf > /dev/null <<'CONFIG'
[Service]
Environment=NETCONTRACT_JUDGE_CONFIG=/home/ec2-user/.config/netcontract/judge-access.json
CONFIG
sudo systemctl daemon-reload
sudo systemctl restart netcontract
sudo systemctl status netcontract --no-pager
```

No Caddy edit is needed for the configuration shown above. If an earlier custom proxy configuration removes Authorization, remove that override; do not inject a fake authenticated-user header.

Open `https://3-25-74-9.sslip.io/` and `/alexa`. The existing project remains accessible at `/salesforce?project=27c291fbf0f248f591e0cfc9781390cc`. Refresh existing browser tabs. Salesforce CLI must be on the service PATH and authenticated as the service user (`ec2-user`) for `hackfest-developer`. The previously configured service HOME/PATH and workspace remain unchanged. Do not run the application as root.

Verify the public record preview no longer returns 403, then perform check-only validation. Actual deploy/sync still needs the explicit reviewed controls. A mocked regression covers public upload, saved review, record preview, validation, deployment, job polling and Alexa reads; development did not change live Salesforce or AWS resources.

## Troubleshooting and rotation

- **401 after the Caddy login:** the app and Caddy credentials differ. Rerun the helper with the same password/username, then restart NetContract. Do not paste passwords or Authorization headers into logs or chat.
- **403:** verify the exact configured HTTPS host and that the browser request sends its Origin/custom action header. Do not remove those checks.
- **503:** the service cannot read a valid verifier configuration; check the path and file owner (`ec2-user`). Malformed or missing configured files deny public requests.
- **CLI unavailable:** inspect `command -v sf` in EC2 and include its installation directory in the NetContract service PATH.
- **No published workspace:** preserve the EC2 `workspace` directory and activate a reviewed completed sync, or complete the normal reviewed deploy-and-sync flow.

To rotate the password, update Caddy's password hash and rerun the helper, then reload Caddy and restart NetContract. The verifier is local configuration and must never be committed. The existing `.gitignore` excludes the application workspace; this verifier lives outside the repo. Preserve both workspace and Salesforce authorization when replacing the instance.

Unset `NETCONTRACT_JUDGE_CONFIG` and restart to disable app judge mode. The original local-only Salesforce restrictions then apply again; retain the Caddy gate or stop public routing. Engineer access through localhost and the SSH tunnel remains available even if the hosted verifier is misconfigured.
