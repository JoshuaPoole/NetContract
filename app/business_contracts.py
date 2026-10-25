"""Review-only business-contract and privacy inventory models.

Business contracts are separate from technical payload/PI field discovery.
Nothing in this module authorizes execution, approval, or deletion.
"""
from typing import Literal
from pydantic import BaseModel, Field, model_validator


ReviewStatus = Literal["review", "approved", "rejected"]


class SourceEvidence(BaseModel):
    source_file: str
    reference: str = ""


class BusinessContract(BaseModel):
    contract_id: str
    kind: Literal["incident", "dip", "execution_policy", "approval_rule", "workflow"]
    name: str
    evidence: list[SourceEvidence] = Field(min_length=1)
    status: ReviewStatus = "review"
    dependencies: list[str] = Field(default_factory=list)
    proposed_salesforce_object: str | None = None


class PrivacyField(BaseModel):
    source_field: str
    source_system: str
    classification: Literal["unknown", "personal", "sensitive", "non_personal"] = "unknown"
    evidence: list[SourceEvidence] = Field(min_length=1)
    status: ReviewStatus = "review"
    retention_hours: int | None = Field(default=None, ge=1)
    retention_start_event: Literal["collected", "workflow_completed"] | None = None
    disposition: Literal["delete", "anonymize"] | None = None

    @model_validator(mode="after")
    def validate_retention(self):
        values = (self.retention_hours, self.retention_start_event, self.disposition)
        if any(value is not None for value in values) and not all(value is not None for value in values):
            raise ValueError("Retention duration, start event and disposition must be configured together")
        return self


class ApplicationBlueprint(BaseModel):
    schema_version: str = "1.0"
    source_repository: str
    business_contracts: list[BusinessContract] = Field(default_factory=list)
    privacy_fields: list[PrivacyField] = Field(default_factory=list)
    execution_enabled: bool = False
    deletion_enabled: bool = False

    @model_validator(mode="after")
    def require_reviewed_nonexecuting_blueprint(self):
        if self.execution_enabled or self.deletion_enabled:
            raise ValueError("Blueprints cannot enable execution or personal-data deletion")
        ids = [contract.contract_id for contract in self.business_contracts]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate business contract IDs")
        return self

