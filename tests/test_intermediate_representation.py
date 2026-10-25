"""Typed IR is evidence-backed and never fabricates data-flow edges."""
import zipfile

from app.intermediate_representation import build_repository_ir


def test_ir_contains_models_endpoints_and_source_evidence(tmp_path):
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("sample/models.py",
                   "from pydantic import BaseModel\n"
                   "class Customer(BaseModel):\n"
                   "    email: str\n"
                   "    age: int\n")
        z.writestr("sample/api.py",
                   "from fastapi import FastAPI\n"
                   "app = FastAPI()\n"
                   "@app.get('/customers')\n"
                   "def customers():\n"
                   "    return []\n")
    ir = build_repository_ir(archive)
    assert ir.static_only is True
    assert ir.edges == []
    models = [n for n in ir.nodes if n.kind == "model_candidate"]
    endpoints = [n for n in ir.nodes if n.kind == "api_endpoint"]
    assert len(models) == 1
    assert endpoints
    assert models[0].fields[0].evidence.line == 3
    assert models[0].fields[0].pii_candidate is True
    assert all(field.status == "review" for field in models[0].fields)
    assert ir.model_dump()["schema_version"] == "1.0"


def test_ir_does_not_invent_database_lineage(tmp_path):
    archive = tmp_path / "db.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("sample/db.py",
                   "import sqlalchemy\n"
                   "def save(session, obj):\n"
                   "    session.add(obj)\n")
    ir = build_repository_ir(archive)
    assert any(n.kind == "persistence_candidate" for n in ir.nodes)
    assert ir.edges == []

