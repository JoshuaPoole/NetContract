"""Review-only grouping of source representations into canonical business concepts.

Groups preserve source contracts and never approve storage or Salesforce metadata.
"""
from pydantic import BaseModel, Field

from .contract_classification import ClassifiedModel
from .procedure_catalog import is_procedure_name, PROCEDURE_CONCEPT


class CanonicalEntityCandidate(BaseModel):
    concept: str
    representations: list[ClassifiedModel] = Field(default_factory=list)
    status: str = "review"
    persistence: str = "unverified"
    proposed_salesforce_object: None = None


def group_canonical_entities(models: list[ClassifiedModel]) -> list[CanonicalEntityCandidate]:
    """Group obvious variants only; do not merge arbitrary similar model names."""
    groups: dict[str, list[ClassifiedModel]] = {}
    for model in models:
        if model.role != "business_entity_candidate":
            continue
        normalized = model.name.lower().replace("_", "")
        if "incident" in normalized:
            concept = "Incident"
        elif "actionplan" in normalized:
            concept = "ActionPlan"
        elif "approval" in normalized:
            concept = "Approval"
        elif "executionstatus" in normalized:
            concept = "ExecutionStatus"
        elif is_procedure_name(model.name) or normalized.endswith("dip"):
            concept = PROCEDURE_CONCEPT
        else:
            concept = model.name
        groups.setdefault(concept, []).append(model)
    return [
        CanonicalEntityCandidate(
            concept=concept,
            representations=sorted(group, key=lambda item: (item.source_file, item.name)),
            persistence="candidate_operation_evidence"
            if any(item.persistence == "candidate_operation_evidence" for item in group)
            else "unverified",
        )
        for concept, group in sorted(groups.items())
    ]


