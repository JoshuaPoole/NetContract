"""Regression tests for offline reviewed canonical metadata export."""
import pytest

from app.reviewed_metadata import (
    ReviewedCanonicalPlan, build_reviewed_analysis, export_reviewed_metadata,
)


def plan(entity_status="review", field_status="review", source="IncomingIncident.id"):
    return ReviewedCanonicalPlan(
        repository="mim.zip", repository_id="test-repository",
        entities=[{
            "concept": "Incident",
            "source_representations": ["IncomingIncident", "HistoricalIncident"],
            "evidence": ["models.py:1"],
            "status": entity_status,
            "fields": [{
                "source": source, "target": "IncidentId", "data_type": "Text",
                "evidence": "models.py:3", "status": field_status,
            }],
        }],
    )


def test_unreviewed_entity_never_generates_metadata(tmp_path):
    with pytest.raises(ValueError, match="No approved"):
        export_reviewed_metadata(plan(field_status="approved"), tmp_path)


def test_unreviewed_field_never_generates_metadata(tmp_path):
    with pytest.raises(ValueError, match="No approved"):
        export_reviewed_metadata(plan(entity_status="approved"), tmp_path)


def test_approved_entity_and_field_generate_offline(tmp_path):
    count = export_reviewed_metadata(
        plan(entity_status="approved", field_status="approved"), tmp_path
    )
    assert count == 1
    assert len(list(tmp_path.rglob("*.object-meta.xml"))) == 1
    assert len(list(tmp_path.rglob("*.field-meta.xml"))) == 1


def test_unrelated_technical_field_rejected():
    with pytest.raises(ValueError, match="not linked"):
        build_reviewed_analysis(plan(
            entity_status="approved", field_status="approved",
            source="PipelineJob.internal_state",
        ))


def test_duplicate_approved_canonical_entities_rejected():
    reviewed = plan(entity_status="approved", field_status="approved")
    reviewed.entities.append(reviewed.entities[0].model_copy(deep=True))
    with pytest.raises(ValueError, match="Duplicate"):
        build_reviewed_analysis(reviewed)

