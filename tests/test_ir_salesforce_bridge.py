"""Ensure IR-to-Salesforce metadata export respects explicit approvals."""
import zipfile

import pytest

from app.intermediate_representation import build_repository_ir
from app.ir_salesforce_bridge import ir_to_analysis, export_approved_metadata


def sample_archive(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("app/models.py",
                   "from pydantic import BaseModel\n"
                   "class Customer(BaseModel):\n"
                   "    email: str\n"
                   "    age: int\n")


def test_ir_fields_default_to_review(tmp_path):
    archive = tmp_path / "sample.zip"
    sample_archive(archive)
    ir = build_repository_ir(archive)
    analysis = ir_to_analysis(ir)
    assert analysis.modules
    assert all(f.status == "review" for m in analysis.modules for f in m.fields)


def test_approved_field_only_generates_metadata(tmp_path):
    archive = tmp_path / "sample.zip"
    sample_archive(archive)
    analysis, count = export_approved_metadata(archive, tmp_path / "metadata", {"Customer.email"})
    assert count == 1
    assert [f.status for f in analysis.modules[0].fields] == ["approved", "review"]
    files = list((tmp_path / "metadata").rglob("*.field-meta.xml"))
    assert len(files) == 1
    assert "Email" in files[0].name


def test_unknown_approval_rejected(tmp_path):
    archive = tmp_path / "sample.zip"
    sample_archive(archive)
    with pytest.raises(ValueError, match="Unknown source"):
        export_approved_metadata(archive, tmp_path / "metadata", {"Customer.nonexistent"})


def test_no_approval_rejected(tmp_path):
    archive = tmp_path / "sample.zip"
    sample_archive(archive)
    with pytest.raises(ValueError, match="explicit field approval"):
        export_approved_metadata(archive, tmp_path / "metadata", set())

