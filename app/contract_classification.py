"""Conservative, offline classification of static repository model candidates.

A name is never sufficient evidence of persistence. This inventory cannot
approve Salesforce objects, fields, retention, or execution.
"""
from pydantic import BaseModel, Field

from .intermediate_representation import RepositoryIR, evidence_reference
from .procedure_catalog import is_procedure_name


class ClassifiedModel(BaseModel):
    name: str
    source_file: str
    role: str
    persistence: str = "unverified"
    evidence: list[str] = Field(default_factory=list)
    requires_review: bool = True


def classify_models(ir: RepositoryIR) -> list[ClassifiedModel]:
    """Classify technical model roles without asserting database ownership."""
    results = []
    hints = {}
    for operation in ir.nodes:
        if operation.kind != "persistence_candidate":
            continue
        if not operation.entity_hint or not operation.entity_evidence:
            continue
        key = operation.entity_hint.split(".")[-1].lower()
        hints.setdefault(key, []).append(
            f"{operation.evidence.source_file}:{operation.evidence.line or 1} "
            f"({operation.persistence_operation}; {operation.entity_evidence})"
        )
    for node in ir.nodes:
        if node.kind != "model_candidate":
            continue
        name = node.name.lower()
        if name.endswith(("request", "response", "payload")):
            role = "api_or_integration_contract"
        elif any(token in name for token in ("pipeline", "profile", "inspection", "analysisresult")):
            role = "processing_model"
        elif is_procedure_name(node.name):
            role = "business_entity_candidate"
        elif any(token in name for token in ("incident", "actionplan", "approval", "executionstatus", "dip")):
            role = "business_entity_candidate"
        else:
            role = "unclassified"
        supporting = hints.get(name, [])
        results.append(ClassifiedModel(
            name=node.name,
            source_file=node.evidence.source_file,
            role=role,
            persistence="candidate_operation_evidence" if supporting else "unverified",
            evidence=[evidence_reference(node.evidence)] + supporting,
        ))
    return results


