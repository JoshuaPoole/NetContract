"""Opt-in, loopback-only GitLab MCP discovery endpoint.

The existing ZIP upload endpoint is unchanged. This endpoint uses the local
GitLabCommunity stdio server and persists the same review-only artifacts.
"""
import hashlib
import json
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .architecture_workflow import ArchitectureWorkflow, Evidence, Stage, StageDecision
from .discovery_inventory import build_inventory_from_entries
from .gitlab_mcp_local import discover_input_via_local_mcp
from .intermediate_representation import build_repository_ir_entries
from .ir_salesforce_bridge import ir_to_analysis
from .judge_access import local_request
from .business_discovery import discover_business_entries

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
        source_input = await discover_input_via_local_mcp(source.project_path, source.ref)
        entries = list(source_input.entries())
        digest = hashlib.sha256(
            json.dumps(
                {"project": source.project_path, "ref": source.ref, "files": entries},
                separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        project_id = uuid.uuid4().hex
        ir = build_repository_ir_entries(entries, source.project_path)
        business = discover_business_entries(entries, source.project_path)
        inventory = build_inventory_from_entries(
            entries, business["blueprint"]["business_contracts"], business["warnings"]
        )
        analysis = ir_to_analysis(ir)
        analysis.repository_id = digest
        from .main import DATA
        (DATA / f"{project_id}.json").write_text(analysis.model_dump_json(indent=2))
        (DATA / f"{project_id}.ir.json").write_text(ir.model_dump_json(indent=2))
        (DATA / f"{project_id}.discovery.json").write_text(json.dumps(inventory))
        workflow = ArchitectureWorkflow(
            source_kind="repository", source_digest=digest,
            decisions=[StageDecision(
                stage=Stage.DISCOVER,
                evidence=[Evidence(source_file=source.project_path, reference="sha256:" + digest)],
                proposal={"candidate_count": len(ir.nodes)}, validated=True,
            )],
        )
        (DATA / f"{project_id}.workflow.json").write_text(workflow.model_dump_json(indent=2))
        return {"project_id": project_id, "analysis": analysis, "ir": ir.model_dump(),
                "inventory": inventory, "source": {"kind": "gitlab_mcp",
                "project_path": source.project_path, "ref": source.ref}}
    except (ValueError, RuntimeError):
        # Avoid exposing subprocess logs, remote errors, or credentials to HTTP clients.
        raise HTTPException(502, "GitLab MCP discovery failed; inspect sanitized server logs") from None
