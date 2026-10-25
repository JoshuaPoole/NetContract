"""Bridge evidence-backed IR field proposals into existing Salesforce review workflow.

No field is approved implicitly. Approval must be explicit and evidence-bound.
"""
import hashlib
from pathlib import Path

from .intermediate_representation import evidence_reference, RepositoryIR, build_repository_ir
from .models import Analysis, FieldMapping, Module
from .salesforce import generate_metadata


def ir_to_analysis(ir: RepositoryIR, approved_sources: set[str] | None = None) -> Analysis:
    """Convert IR model candidates to an Analysis with explicit field approvals."""
    approved_sources = approved_sources or set()
    known_sources = {
        field.source for node in ir.nodes if node.kind == "model_candidate"
        for field in node.fields
    }
    source_counts = {}
    for node in ir.nodes:
        if node.kind == "model_candidate":
            for field in node.fields:
                source_counts[field.source] = source_counts.get(field.source, 0) + 1
    ambiguous = sorted(source for source in approved_sources if source_counts.get(source, 0) > 1)
    if ambiguous:
        raise ValueError(
            "Ambiguous source fields occur in multiple files; approval refused: " + ", ".join(ambiguous)
        )
    unknown = approved_sources - known_sources
    if unknown:
        raise ValueError("Unknown source fields cannot be approved: " + ", ".join(sorted(unknown)))
    modules = []
    for node in ir.nodes:
        if node.kind != "model_candidate":
            continue
        fields = [
            FieldMapping(
                source=field.source,
                target=field.proposed_target,
                data_type=field.proposed_type,
                pii=field.pii_candidate,
                status="approved" if field.source in approved_sources else "review",
                evidence=evidence_reference(field.evidence),
            )
            for field in node.fields
        ]
        modules.append(Module(name=node.name, source_file=node.evidence.source_file, fields=fields))
    return Analysis(
        repository=ir.repository,
        repository_id=hashlib.sha256(ir.model_dump_json().encode("utf-8")).hexdigest(),
        compatible=bool(modules),
        reasons=["Imported typed static IR; no runtime data flow is proven"],
        modules=modules,
        integrations=[],
        warnings=ir.warnings,
    )


def export_approved_metadata(
    repository_zip: Path, destination: Path, approved_sources: set[str]
) -> tuple[Analysis, int]:
    """Build IR then generate only explicitly approved Salesforce metadata.

    This function writes files locally and never invokes Salesforce CLI or APIs.
    """
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("Destination must be empty")
    ir = build_repository_ir(repository_zip)
    analysis = ir_to_analysis(ir, approved_sources)
    if not approved_sources:
        raise ValueError("At least one explicit field approval is required")
    count = generate_metadata(analysis, destination, analysis.repository_id)
    if count == 0:
        raise ValueError("No approved metadata generated")
    return analysis, count


