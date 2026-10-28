"""Regression tests for opt-in GitLab discovery and its safety gates."""
import io
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app import gitlab_discover_api as module


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NETCONTRACT_LOCAL_MCP_DISCOVERY", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/discover/gitlab", json={
            "project_path": "netcontractcyber-group/NetContract", "ref": "main"
        })
    assert response.status_code == 403


def test_rejects_non_allowlisted_project(monkeypatch):
    monkeypatch.setenv("NETCONTRACT_LOCAL_MCP_DISCOVERY", "1")
    monkeypatch.setenv("NETCONTRACT_MCP_ALLOWED_PROJECT", "netcontractcyber-group/NetContract")
    monkeypatch.setattr(module, "local_request", lambda request: True)
    with TestClient(app) as client:
        response = client.post("/api/discover/gitlab", json={
            "project_path": "other-group/OtherRepo", "ref": "main"
        })
    assert response.status_code == 403


def test_gitlab_snapshot_uses_existing_zip_ingestion(monkeypatch, tmp_path):
    import zipfile
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("app/models.py", "class Incident:\n    status: str\n")
    monkeypatch.setenv("NETCONTRACT_LOCAL_MCP_DISCOVERY", "1")
    monkeypatch.setenv("NETCONTRACT_MCP_ALLOWED_PROJECT", "netcontractcyber-group/NetContract")
    monkeypatch.setattr(module, "local_request", lambda request: True)
    monkeypatch.setattr(module, "discover_via_local_mcp", AsyncMock(return_value=output.getvalue()))
    from app import main
    monkeypatch.setattr(main, "DATA", tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/discover/gitlab", json={
            "project_path": "netcontractcyber-group/NetContract", "ref": "main"
        })
    assert response.status_code == 200, response.text
    assert response.json()["source"]["kind"] == "gitlab_mcp"
    assert response.json()["project_id"]
