"""Read-only GitLab MCP connectivity probe.

This probe accepts a separately acquired OAuth token with the GitLab 'mcp'
scope. It never prints or persists the token and never invokes remote tools.
"""
from __future__ import annotations

import os

import httpx

from app.gitlab_mcp_policy import GITLAB_MCP_URL


def probe_gitlab_mcp(token: str, *, transport: httpx.BaseTransport | None = None) -> dict:
    """Initialize MCP and list advertised tools; do not execute any tool."""
    if not token or not token.strip():
        raise ValueError("An OAuth token with the mcp scope is required")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "X-Gitlab-Enabled-Mcp-Server-Toolsets": "core,repository",
    }
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "netcontract-readonly-probe", "version": "0.1.0"},
        },
    }
    with httpx.Client(timeout=15, transport=transport, follow_redirects=False) as client:
        response = client.post(GITLAB_MCP_URL, headers=headers, json=payload)
        response.raise_for_status()
        if "text/event-stream" in response.headers.get("content-type", ""):
            raise ValueError("Server returned an SSE stream; use a full MCP client for streaming")
        data = response.json()
        if "error" in data:
            raise ValueError("GitLab MCP initialization rejected")
        result = data.get("result")
        if not isinstance(result, dict) or not result.get("protocolVersion"):
            raise ValueError("Unexpected GitLab MCP initialization response")
        session = response.headers.get("mcp-session-id")
        next_headers = dict(headers)
        next_headers["MCP-Protocol-Version"] = result["protocolVersion"]
        if session:
            next_headers["Mcp-Session-Id"] = session
        # MCP initialized notification precedes tools/list.
        client.post(
            GITLAB_MCP_URL,
            headers=next_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        ).raise_for_status()
        tools_response = client.post(
            GITLAB_MCP_URL,
            headers=next_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        tools_response.raise_for_status()
        if "text/event-stream" in tools_response.headers.get("content-type", ""):
            raise ValueError("Server returned an SSE stream; use a full MCP client for streaming")
        tools_data = tools_response.json()
        if "error" in tools_data or not isinstance(tools_data.get("result", {}).get("tools"), list):
            raise ValueError("GitLab MCP tools/list failed")
        return {
            "connected": True,
            "protocol_version": result["protocolVersion"],
            "server_name": result.get("serverInfo", {}).get("name", "GitLab"),
            "advertised_tools": sorted(t["name"] for t in tools_data["result"]["tools"] if isinstance(t, dict) and isinstance(t.get("name"), str)),
            "tool_calls_executed": 0,
        }


if __name__ == "__main__":
    import json
    token = os.environ.get("GITLAB_MCP_OAUTH_TOKEN", "")
    if not token:
        raise SystemExit("Set GITLAB_MCP_OAUTH_TOKEN locally (OAuth mcp scope); do not commit it.")
    try:
        print(json.dumps(probe_gitlab_mcp(token), indent=2))
    except (httpx.HTTPError, ValueError) as exc:
        # Never print request headers or token-bearing exceptions.
        raise SystemExit(f"GitLab MCP probe failed: {type(exc).__name__}") from None
