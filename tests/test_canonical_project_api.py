"""Project approvals must match server-stored source evidence."""
import json

from fastapi.testclient import TestClient

from app.intermediate_representation import Evidence, IRField, IRNode, RepositoryIR
from app.main import app

client = TestClient(app)


def setup_project(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPPER_WORKSPACE", str(tmp_path))
    monkeypatch.setattr("app.main.DATA", tmp_path)
    (tmp_path / "abc123.json").write_text(json.dumps({"repository": "sample.zip", "repository_id": "hash123", "compatible": True, "reasons": [], "modules": [], "integrations": []}))
    ir = RepositoryIR(repository="sample.zip", nodes=[
        IRNode(id="model:0", kind="model_candidate", name="Incident",
               evidence=Evidence(source_file="models.py", line=1),
               fields=[IRField(source="Incident.id", proposed_target="Id",
                               proposed_type="Text",
                               evidence=Evidence(source_file="models.py", line=2))]),
    ])
    (tmp_path / "abc123.ir.json").write_text(ir.model_dump_json())
    return {
        "repository": "sample.zip", "repository_id": "hash123",
        "entities": [{
            "concept": "Incident", "source_representations": ["Incident"],
            "evidence": ["models.py:1"], "status": "approved",
            "fields": [{"source": "Incident.id", "target": "IncidentId",
                        "data_type": "Text", "evidence": "models.py:2",
                        "status": "approved"}],
        }],
    }


def test_project_review_requires_matching_evidence(tmp_path, monkeypatch):
    plan = setup_project(tmp_path, monkeypatch)
    plan["entities"][0]["fields"][0]["evidence"] = "fake.py:99"
    response = client.put("/api/projects/abc123/canonical/review", json=plan)
    assert response.status_code == 400
    assert not (tmp_path / "abc123.canonical.json").exists()


def test_project_review_and_metadata_zip(tmp_path, monkeypatch):
    plan = setup_project(tmp_path, monkeypatch)
    saved = client.put("/api/projects/abc123/canonical/review", json=plan)
    assert saved.status_code == 200, saved.text
    response = client.get("/api/projects/abc123/canonical/metadata.zip")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"PK")


def test_legacy_endpoints_cannot_bypass_review(tmp_path, monkeypatch):
    setup_project(tmp_path, monkeypatch)
    assert client.get("/api/projects/abc123/metadata.zip").status_code == 410
    assert client.post("/api/projects/abc123/deploy").status_code == 403
    assert client.get("/api/projects/abc123/canonical/metadata.zip").status_code == 409



def test_candidates_seed_unapproved_review_and_reload_saved_decisions(tmp_path, monkeypatch):
    plan = setup_project(tmp_path, monkeypatch)
    first = client.get("/api/projects/abc123/canonical/candidates").json()
    assert first["review_saved"] is False
    draft = first["review_plan"]
    assert draft["repository_id"] == "hash123"
    assert draft["entities"][0]["status"] == "review"
    assert draft["entities"][0]["fields"][0]["evidence"] == "models.py:2"
    assert draft["entities"][0]["fields"][0]["status"] == "review"
    assert client.put("/api/projects/abc123/canonical/review", json=plan).status_code == 200
    loaded = client.get("/api/projects/abc123/canonical/candidates").json()
    assert loaded["review_saved"] is True
    assert loaded["review_plan"]["entities"][0]["fields"][0]["target"] == "IncidentId"


def test_export_excludes_unapproved_fields_and_includes_review_evidence(tmp_path, monkeypatch):
    import io
    import zipfile

    plan = setup_project(tmp_path, monkeypatch)
    path = tmp_path / "abc123.ir.json"
    ir = RepositoryIR.model_validate_json(path.read_text())
    ir.nodes[0].fields.append(IRField(
        source="Incident.email", proposed_target="Email", proposed_type="Email",
        pii_candidate=True, evidence=Evidence(source_file="models.py", line=3),
    ))
    path.write_text(ir.model_dump_json())
    plan["entities"][0]["fields"].append({
        "source": "Incident.email", "target": "Email", "data_type": "Email",
        "pii_candidate": True, "evidence": "models.py:3", "status": "review",
    })
    assert client.put("/api/projects/abc123/canonical/review", json=plan).status_code == 200
    response = client.get("/api/projects/abc123/canonical/metadata.zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        fields = [name for name in archive.namelist() if name.endswith(".field-meta.xml")]
        assert len(fields) == 1 and fields[0].endswith("IncidentId__c.field-meta.xml")
        assert json.loads(archive.read("canonical-review.json"))["entities"][0]["evidence"] == ["models.py:1"]
    plan["entities"][0]["fields"][1].update(status="approved", pii_candidate=False)
    assert client.put("/api/projects/abc123/canonical/review", json=plan).status_code == 400
    plan["entities"][0]["fields"][1]["pii_candidate"] = True
    assert client.put("/api/projects/abc123/canonical/review", json=plan).status_code == 200


def test_saved_empty_review_cannot_export_and_wrong_identity_cannot_reload(tmp_path, monkeypatch):
    plan = setup_project(tmp_path, monkeypatch)
    plan["entities"][0]["status"] = "review"
    assert client.put("/api/projects/abc123/canonical/review", json=plan).status_code == 200
    assert client.get("/api/projects/abc123/canonical/metadata.zip").status_code == 400
    plan["repository_id"] = "different"
    (tmp_path / "abc123.canonical.json").write_text(json.dumps(plan))
    assert client.get("/api/projects/abc123/canonical/candidates").status_code == 409


def test_zip_scan_to_explicit_review_and_scoped_export(tmp_path, monkeypatch):
    import io
    import zipfile

    monkeypatch.setenv("MAPPER_WORKSPACE", str(tmp_path))
    monkeypatch.setattr("app.main.DATA", tmp_path)
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("legacy/models.py", "from pydantic import BaseModel\nclass Incident(BaseModel):\n    ticket_id: str\n    email: str\n")
        archive.writestr("legacy/api.py", "from pydantic import BaseModel\nclass IncidentResponse(BaseModel):\n    status: str\n")
    uploaded = client.post("/api/analyze", files={"file": ("legacy.zip", source.getvalue(), "application/zip")})
    assert uploaded.status_code == 200, uploaded.text
    project_id = uploaded.json()["project_id"]
    base = f"/api/projects/{project_id}/canonical"
    candidates = client.get(base + "/candidates").json()
    plan = candidates["review_plan"]
    assert len(plan["entities"]) == 1  # API response is not promoted to an entity.
    entity = plan["entities"][0]
    entity["status"] = "approved"
    chosen = next(field for field in entity["fields"] if field["source"] == "Incident.ticket_id")
    chosen.update(status="approved", target="TicketReference")
    assert next(field for field in entity["fields"] if field["source"] == "Incident.email")["pii_candidate"]
    assert client.put(base + "/review", json=plan).status_code == 200
    exported = client.get(base + "/metadata.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        fields = [name for name in archive.namelist() if name.endswith(".field-meta.xml")]
        assert len(fields) == 1 and fields[0].endswith("TicketReference__c.field-meta.xml")
    assert client.post(f"/api/projects/{project_id}/deploy").status_code == 403

