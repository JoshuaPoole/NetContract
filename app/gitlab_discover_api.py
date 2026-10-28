"""Opt-in, loopback-only GitLab MCP discovery using the existing ZIP scanner."""
import io
import os

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .gitlab_mcp_local import discover_via_local_mcp
from .judge_access import local_request

router = APIRouter()


class GitLabDiscoveryRequest(BaseModel):
    project_path: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+$")
    ref: str = Field(default="main", min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_./-]+$")


@router.post("/api/discover/gitlab")
async def discover_gitlab(request: Request, source: GitLabDiscoveryRequest):
    if os.environ.get("NETCONTRACT_LOCAL_MCP_DISCOVERY") != "1" or not local_request(request):
        raise HTTPException(403, "Local MCP discovery is disabled")
    allowed = os.environ.get("NETCONTRACT_MCP_ALLOWED_PROJECT", "")
    if not allowed or source.project_path != allowed:
        raise HTTPException(403, "GitLab project is not allowlisted")
    try:
        archive = await discover_via_local_mcp(source.project_path, source.ref)
        if len(archive) > 20_000_000:
            raise ValueError("GitLab snapshot exceeds upload limit")
        # Reuse the existing ZIP scanners and review artifacts.
        from .main import analyze
        result = await analyze(UploadFile(file=io.BytesIO(archive), filename="gitlab-snapshot.zip"))
        result["source"] = {"kind": "gitlab_mcp", "project_path": source.project_path, "ref": source.ref}
        return result
    except (ValueError, RuntimeError, HTTPException):
        raise HTTPException(502, "GitLab MCP discovery failed; inspect sanitized server logs") from None
