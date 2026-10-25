"""Offline checks for distinct business contracts and PI lifecycle proposals."""
import pytest
from pydantic import ValidationError

from app.business_contracts import ApplicationBlueprint, BusinessContract, PrivacyField, SourceEvidence


EVIDENCE = [SourceEvidence(source_file="data/input/change_repository/dips.json")]


def test_business_contract_is_review_only_by_default():
    blueprint = ApplicationBlueprint(
        source_repository="MIMUseCase",
        business_contracts=[BusinessContract(
            contract_id="dip-001", kind="dip", name="Remediation procedure", evidence=EVIDENCE
        )],
        privacy_fields=[PrivacyField(
            source_field="payload_path", source_system="MIM", evidence=EVIDENCE
        )],
    )
    assert blueprint.business_contracts[0].status == "review"
    assert blueprint.privacy_fields[0].classification == "unknown"
    assert blueprint.execution_enabled is False
    assert blueprint.deletion_enabled is False


def test_retention_proposal_requires_complete_explicit_configuration():
    with pytest.raises(ValidationError, match="configured together"):
        PrivacyField(source_field="email", source_system="MIM", evidence=EVIDENCE, retention_hours=48)
    candidate = PrivacyField(
        source_field="email", source_system="MIM", evidence=EVIDENCE,
        classification="personal", retention_hours=48,
        retention_start_event="workflow_completed", disposition="delete"
    )
    assert candidate.retention_hours == 48
    assert candidate.status == "review"


def test_no_execution_or_deletion_is_enabled_from_blueprint():
    with pytest.raises(ValidationError, match="cannot enable"):
        ApplicationBlueprint(source_repository="MIM", deletion_enabled=True)
    with pytest.raises(ValidationError, match="cannot enable"):
        ApplicationBlueprint(source_repository="MIM", execution_enabled=True)


def test_evidence_and_unique_contract_ids_required():
    with pytest.raises(ValidationError):
        BusinessContract(contract_id="dip", kind="dip", name="DIP", evidence=[])
    contract = BusinessContract(contract_id="dip", kind="dip", name="DIP", evidence=EVIDENCE)
    with pytest.raises(ValidationError, match="Duplicate"):
        ApplicationBlueprint(source_repository="MIM", business_contracts=[contract, contract])

