"""Local stdio MCP client for read-only GitLab repository discovery.

Requires the separately installed 'mcp' Python SDK and a configured local
GitLabCommunity MCP server executable. No tokens are logged or persisted.
"""
import json
import os
from pathlib import Path

from .repository_input import RepositorySource, repository_input


def _unwrap(result):
    if result.is_error:
        raise ValueError("GitLab MCP tool failed")
    if getattr(result, "structured_content", None) is not None:
        value = result.structured_content
    else:
        blocks = [x.text for x in result.content if getattr(x, "type", None) == "text"]
        if not blocks:
            raise ValueError("GitLab MCP returned no text")
        value = json.loads(blocks[0])
    if isinstance(value, dict) and "result" in value:
        value = value["result"]
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    return value


async def discover_input_via_local_mcp(project_path: str, ref: str):
    """Retrieve a bounded repository snapshot via GitLabCommunity stdio MCP.

    The server must be launched locally by the backend, not borrowed from VS Code.
    Tool names and schemas are inspected dynamically to avoid guessing.
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("Install the Python mcp SDK to enable local discovery") from exc

    if not os.environ.get("GITLAB_PERSONAL_ACCESS_TOKEN"):
        raise RuntimeError("GITLAB_PERSONAL_ACCESS_TOKEN is required in backend environment")
    command = os.environ.get("NETCONTRACT_MCP_COMMAND", "npx")
    args = os.environ.get("NETCONTRACT_MCP_ARGS", "-y @zereight/mcp-gitlab@2.3.12").split()
    env = {**os.environ}
    async with stdio_client(StdioServerParameters(command=command, args=args, env=env)) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            catalog = {t.name: t for t in (await session.list_tools()).tools}
            tree_tool = next((n for n in ("list_repository_tree", "get_repository_tree") if n in catalog), None)
            file_tool = next((n for n in ("get_repository_file", "get_file_content", "get_file_contents") if n in catalog), None)
            if not tree_tool or not file_tool:
                raise RuntimeError("Required read-only repository tools unavailable")
            # Tool schemas vary by MCP server version; validate against advertised schema.
            async def call(name, arguments):
                properties = catalog[name].input_schema.get("properties", {})
                required = set(catalog[name].input_schema.get("required", []))
                values = {k: v for k, v in arguments.items() if k in properties}
                if not required.issubset(values):
                    raise RuntimeError("Unsupported GitLabCommunity MCP tool schema")
                return _unwrap(await session.call_tool(name, values))
            common = {"project_id": project_path, "project_path": project_path, "ref": ref, "ref_name": ref}
            tree = await call(tree_tool, {**common, "recursive": True, "per_page": 100})
            if not isinstance(tree, list):
                raise RuntimeError("Unexpected MCP repository tree response")
            files = {}
            for item in tree:
                if item.get("type") != "blob":
                    continue
                path = item.get("path")
                if not isinstance(path, str):
                    continue
                from .gitlab_mcp_snapshot import _safe_path
                from .discovery import SOURCE_SUFFIXES, CONFIG_SUFFIXES, INFRA_NAMES
                from .container_discovery import is_dockerfile
                try:
                    safe = _safe_path(path)
                except ValueError:
                    continue
                p = Path(safe)
                if p.suffix.lower() not in SOURCE_SUFFIXES | CONFIG_SUFFIXES and p.name.lower() not in INFRA_NAMES and not is_dockerfile(safe):
                    continue
                value = await call(file_tool, {**common, "file_path": safe, "path": safe})
                if isinstance(value, dict):
                    value = value.get("content")
                if not isinstance(value, str):
                    raise RuntimeError("Unexpected MCP file content response")
                files[safe] = value
            return repository_input(RepositorySource(project_path, ref, "gitlab_mcp"), files.items())
async def discover_via_local_mcp(project_path: str, ref: str) -> bytes:
    """Temporary compatibility bridge for existing API tests and callers."""
    import io
    import zipfile
    source = await discover_input_via_local_mcp(project_path, ref)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in source.files:
            archive.writestr(item.path, item.content)
    return output.getvalue()
