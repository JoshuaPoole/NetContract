# Instance 2 MCP service configuration (no credentials)

This directory contains a **template**, not an active configuration. Copy it into
the existing `netcontract` systemd service's override directory on Instance 2
only after the adapter tests pass and the correct service has been identified.

## 1. Verify prerequisites and preserve state

```bash
sudo systemctl status netcontract --no-pager
sudo systemctl cat netcontract
git rev-parse HEAD
command -v node
command -v npx
.venv/bin/python -c 'import mcp; print("Python MCP SDK import OK")'
```

Do not replace the service unit or its existing judge-access overrides. Keep
`workspace/`, Salesforce credentials, and Caddy configuration unchanged.

## 2. Install non-secret override

```bash
sudo install -d -m 0755 /etc/systemd/system/netcontract.service.d
sudo install -m 0644 deploy/systemd/20-gitlab-mcp.conf /etc/systemd/system/netcontract.service.d/20-gitlab-mcp.conf
```

The committed template deliberately defaults to **disabled**. Once the
integration test passes, change the value to `1` in the installed copy,
not in the repository.

## 3. Supply the GitLab token separately

Use a root-owned, mode 0600 environment file outside Git (for example
`/etc/netcontract/gitlab-mcp.env`) containing
`GITLAB_PERSONAL_ACCESS_TOKEN=...`. Never paste the token into chat, Git,
logs, or command history. Attach it with a separate systemd override
`EnvironmentFile=/etc/netcontract/gitlab-mcp.env` after confirming its
owner, permissions, and token scope. Use a read-only, least-privilege token.
Do not replace any existing `EnvironmentFile` entries.

## 4. Activate and verify

```bash
sudo systemctl daemon-reload
sudo systemctl restart netcontract
sudo systemctl is-active netcontract
```

Use the existing SSH loopback tunnel to access the GitLab endpoint. Never
publish the endpoint through a new public route. Verify the original judge
URL, ZIP upload and Salesforce review gates. Full instance reboot is not
required. Roll back by changing the installed `NETCONTRACT_LOCAL_MCP_DISCOVERY`
value to `0`, then daemon-reload and restart the service.

Do not paste `systemctl show -p Environment` output if it contains credentials.
