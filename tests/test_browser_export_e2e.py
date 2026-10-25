"""End-to-end browser API workflow: upload, review, save, export."""
import io
import zipfile
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from app.main import app


def _archive():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr(
            "src/customer.py",
            "from pydantic import BaseModel\n"
            "class Customer(BaseModel):\n"
            "    email: str\n"
            "    age: int\n",
        )
    return payload.getvalue()


def test_review_gate_and_metadata_export(tmp_path, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "DATA", tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        files={"file": ("customer.zip", _archive(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ir"]["static_only"] is True
    assert body["ir"]["nodes"]
    project_id = body["project_id"]
    url = f"/api/projects/{project_id}"
    assert client.get(url).status_code == 200

    # No metadata is exported without explicit review approval.
    blocked = client.get(url + "/metadata.zip")
    assert blocked.status_code == 410

    analysis = body["analysis"]
    fields = [field for module in analysis["modules"] for field in module["fields"]]
    assert len(fields) >= 2
    assert all(field["status"] == "review" for field in fields)
    fields[0]["status"] = "approved"
    assert client.put(url, json=analysis).status_code == 200

    result = client.get(url + "/metadata.zip")
    assert result.status_code == 410
    assert client.post(url + "/deploy").status_code == 403

    saved = client.get(url).json()
    assert sum(field["status"] == "approved"
               for module in saved["modules"] for field in module["fields"]) == 1

