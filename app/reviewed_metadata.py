"""Offline Salesforce metadata preview for explicitly reviewed canonical entities.

No repository scan, heuristic classification, or candidate persistence evidence
can approve a Salesforce object or field.
"""
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from .models import Analysis, FieldMapping, Module
from .salesforce import generate_metadata


class ReviewedField(BaseModel):
    source: str
    target: str
    data_type: str = "Text"
    evidence: str
    pii_candidate: bool = False
    status: str = "review"


class ReviewedEntity(BaseModel):
    concept: str
    source_representations: list[str] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    status: str = "review"
    fields: list[ReviewedField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_review(self):
        if self.status not in {"review", "approved", "rejected"}:
            raise ValueError("Invalid entity review status")
        if any(field.status not in {"review", "approved", "rejected"} for field in self.fields):
            raise ValueError("Invalid field review status")
        return self


class ReviewedCanonicalPlan(BaseModel):
    repository: str
    repository_id: str = Field(min_length=1)
    entities: list[ReviewedEntity] = Field(default_factory=list)


def build_reviewed_analysis(plan: ReviewedCanonicalPlan) -> Analysis:
    """Require entity AND field approval before any metadata can be emitted."""
    modules = []
    seen = set()
    for entity in plan.entities:
        if entity.status != "approved":
            continue
        key = entity.concept.casefold()
        if key in seen:
            raise ValueError(f"Duplicate approved canonical entity: {entity.concept}")
        seen.add(key)
        approved_fields = []
        for field in entity.fields:
            if field.status != "approved":
                continue
            if not field.evidence.strip():
                raise ValueError(f"Approved field has no source evidence: {field.source}")
            if not any(field.source.startswith(name + ".") for name in entity.source_representations):
                raise ValueError(f"Field is not linked to a reviewed source representation: {field.source}")
            approved_fields.append(FieldMapping(
                source=field.source, target=field.target, data_type=field.data_type,
                evidence=field.evidence, pii=field.pii_candidate, status="approved",
            ))
        if approved_fields:
            modules.append(Module(name=entity.concept, source_file=entity.evidence[0],
                                  fields=approved_fields))
    return Analysis(repository=plan.repository, repository_id=plan.repository_id,
                    compatible=bool(modules), reasons=["Explicit canonical review"],
                    modules=modules, integrations=[])


def export_reviewed_metadata(plan: ReviewedCanonicalPlan, destination: Path) -> int:
    """Write metadata to a local directory; never invoke Salesforce APIs."""
    analysis = build_reviewed_analysis(plan)
    if not analysis.modules:
        raise ValueError("No approved canonical entity fields")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Destination must be empty")
    return generate_metadata(analysis, destination, plan.repository_id)


