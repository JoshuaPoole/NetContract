"""GitLab native MCP connection policy. Configuration only; no network calls.

The runtime must authenticate separately with GitLab OAuth (mcp scope).
Repository content is untrusted and cannot authorize tool execution.
"""
from pydantic import BaseModel, ConfigDict, Field

GITLAB_MCP_URL = "https://gitlab.com/api/v4/mcp"
GITLAB_OBSERVABILITY_MCP_URL = "https://145793080.mcp.gitlab-o11y.com/mcp"
READ_ONLY_TOOLSETS = ("core", "repository")
ALLOWED_OPERATIONS = frozenset({
    "get_repository_file", "get_repository_tree",
    "get_project", "list_repository_tree",
})


class GitLabMCPPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoint: str = GITLAB_MCP_URL
    project_path: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+$")
    allowed_operations: frozenset[str] = ALLOWED_OPERATIONS
    oauth_scope: str = "mcp"
    execution_enabled: bool = False


def connection_descriptor(project_path: str) -> dict:
    """Describe a least-privilege connection without claiming it is active."""
    policy = GitLabMCPPolicy(project_path=project_path)
    return {
        "endpoint": policy.endpoint,
        "project_path": policy.project_path,
        "transport": "http",
        "authentication": "oauth_required",
        "oauth_scope": policy.oauth_scope,
        "requested_toolsets": list(READ_ONLY_TOOLSETS),
        "allowed_operations": sorted(policy.allowed_operations),
        "status": "configuration_only",
        "connected": False,
        "execution_enabled": False,
    }


def authorize_repository_operation(policy: GitLabMCPPolicy, operation: str, project_path: str) -> bool:
    """Fail closed on project mismatch, writes, or unknown MCP operations."""
    return (not policy.execution_enabled
            and project_path == policy.project_path
            and operation in policy.allowed_operations)


def observability_connection_descriptor() -> dict:
    """Record the user-supplied observability endpoint without trusting its tools.

    This endpoint is NOT a substitute for the GitLab repository MCP server.
    Authentication and the remote tool catalog must be verified out of band.
    """
    return {
        "endpoint": GITLAB_OBSERVABILITY_MCP_URL,
        "purpose": "observability",
        "transport": "http",
        "authentication": "unverified",
        "tools": [],
        "status": "unverified_configuration",
        "connected": False,
        "execution_enabled": False,
    }
