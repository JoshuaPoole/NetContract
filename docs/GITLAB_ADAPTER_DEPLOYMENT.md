# GitLab MCP adapter — Instance 2 deployment checklist

This is a staged, opt-in change. Do not merge or deploy until the regression suite passes.
Instance 1 and the submitted GitLab competition branch are out of scope.

## Before deploying
- Confirm the correct Instance 2 SSH host, checkout and service name.
- Preserve existing `workspace/`, judge access config, systemd overrides and environment files.
- Confirm Node.js/npm/npx and Python are installed on Instance 2.
- Verify `python -m pytest -q` and specifically `python -m pytest -q tests/test_gitlab_adapter_integration.py`.
- Confirm the `mcp` Python SDK imports and that the configured stdio MCP server advertises compatible read-only repository tools.
- Note that `app/gitlab_mcp_local.py` uses `GITLAB_PERSONAL_ACCESS_TOKEN` from the service environment. Use a read-only, least-privilege token; never paste it into Git, logs or chat.

## Deployment (after tests and approval)
1. Record the current commit SHA and preserve the previous checkout for rollback.
2. Deploy the reviewed fix branch to **Instance 2 only**.
3. Within its existing virtualenv, install dependencies with `python -m pip install -r requirements.txt`.
4. Configure `NETCONTRACT_LOCAL_MCP_DISCOVERY=1` and `NETCONTRACT_MCP_ALLOWED_PROJECT=netcontractcyber-group/NetContract` in the protected Instance 2 service environment; leave the feature disabled until ready.
5. Check the installed `npx` and the MCP server version before restarting. The adapter defaults to `npx -y @zereight/mcp-gitlab@2.3.12`.
6. Restart **only** the Instance 2 `netcontract` service using `sudo systemctl restart netcontract` (if that is the verified service name).
7. Verify `systemctl status netcontract`, the existing judge URL and its authentication, and the original ZIP upload workflow. Use the SSH loopback tunnel for GitLab discovery; it is not a public endpoint.
8. Perform a read-only discovery request for the allowlisted project. Review generated artifacts before any Salesforce action.

## Rollback
- Disable `NETCONTRACT_LOCAL_MCP_DISCOVERY` in the service environment.
- Restore the recorded previous commit/checkout and previous dependency environment if needed.
- Restart only the Instance 2 service, then verify the judge URL and original upload workflow.
- Do not delete or reset `workspace/` or judge credentials.

## Known limits
- The local MCP client reads only the first returned repository tree page unless the server provides a complete tree. Large repositories may need pagination support.
- The connector returns a ZIP to the existing static scanner. Source revision is included in the API response, but persisted project identity is currently the ZIP digest.
- This repository-only staging does not verify live AWS credentials, token permissions, network access, or service state.
