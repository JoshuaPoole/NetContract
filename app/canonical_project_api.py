"""Project-scoped, evidence-bound canonical review and offline metadata."""
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .canonical_entities import group_canonical_entities
from .procedure_catalog import IDENTITIES
from .canonical_evidence import validate_plan_against_ir
from .contract_classification import classify_models
from .intermediate_representation import evidence_reference, RepositoryIR
from .reviewed_metadata import (
    ReviewedCanonicalPlan,
    ReviewedEntity,
    ReviewedField,
    export_reviewed_metadata,
)

router = APIRouter()


def project_paths(project_id: str):
    if not project_id.isalnum():
        raise HTTPException(400, "Invalid project ID")
    root = Path(os.environ.get("MAPPER_WORKSPACE", "workspace"))
    project = root / f"{project_id}.json"
    snapshot = root / f"{project_id}.ir.json"
    review = root / f"{project_id}.canonical.json"
    if not project.exists():
        raise HTTPException(404, "Project not found")
    if not snapshot.exists():
        raise HTTPException(409, "Project predates canonical evidence snapshots; re-upload ZIP")
    return project, snapshot, review


def load_ir(snapshot: Path) -> RepositoryIR:
    return RepositoryIR.model_validate_json(snapshot.read_text())


@router.get("/api/projects/{project_id}/canonical/candidates")
def canonical_candidates(project_id: str):
    project, snapshot, review = project_paths(project_id)
    ir = load_ir(snapshot)
    candidates = group_canonical_entities(classify_models(ir))
    original = json.loads(project.read_text())
    entities = []
    for candidate in candidates:
        representations = {(item.name, item.source_file) for item in candidate.representations}
        fields = [ReviewedField(
            source=field.source, target=field.proposed_target,
            data_type=field.proposed_type, pii_candidate=field.pii_candidate,
            external_id=candidate.concept == "DIP" and field.evidence.kind == "json_catalog" and field.proposed_type == "Text" and field.source.rsplit(".", 1)[-1] in IDENTITIES,
            evidence=evidence_reference(field.evidence),
        ) for node in ir.nodes if node.kind == "model_candidate"
            and (node.name, node.evidence.source_file) in representations
            for field in node.fields]
        entities.append(ReviewedEntity(
            concept=candidate.concept,
            source_representations=sorted({item.name for item in candidate.representations}),
            evidence=sorted({ref for item in candidate.representations for ref in item.evidence}),
            fields=fields,
        ))
        if candidate.concept == "DIP":
            # Common procedure properties share one target field, with a real
            # source pointer retained. Catalog records keep every original path.
            unique = {}
            for field in fields:
                key = field.source.rsplit('.', 1)[-1]
                identity_key = ('procedure_identity' if key in IDENTITIES else key, field.data_type)
                if identity_key not in unique or (field.external_id and not unique[identity_key].external_id):
                    unique[identity_key] = field
            entities[-1].fields = list(unique.values())
    plan = ReviewedCanonicalPlan(
        repository=ir.repository, repository_id=original["repository_id"], entities=entities,
    )
    fresh_plan = plan
    review_complete = True
    if review.exists():
        plan = ReviewedCanonicalPlan.model_validate_json(review.read_text())
        if plan.repository_id != original["repository_id"] or plan.repository != ir.repository:
            raise HTTPException(409, "Saved review identity differs from project")
        try:
            validate_plan_against_ir(plan, ir)
        except ValueError as exc:
            raise HTTPException(409, "Saved review no longer matches source evidence") from exc
        known = {entity.concept for entity in plan.entities}
        additions = [entity for entity in fresh_plan.entities if entity.concept not in known]
        plan.entities.extend(additions)
        review_complete = not additions
    return {
        "canonical_entities": [candidate.model_dump() for candidate in candidates],
        "review_plan": plan.model_dump(), "review_saved": review.exists() and review_complete,
        "procedure_catalogs": ir.procedure_catalogs,
    }


@router.put("/api/projects/{project_id}/canonical/review")
def save_canonical_review(project_id: str, plan: ReviewedCanonicalPlan):
    project, snapshot, review = project_paths(project_id)
    original = json.loads(project.read_text())
    if plan.repository_id != original.get("repository_id"):
        raise HTTPException(400, "Repository identity mismatch")
    ir = load_ir(snapshot)
    if plan.repository != ir.repository:
        raise HTTPException(400, "Repository name mismatch")
    try:
        validate_plan_against_ir(plan, ir)
        # Validate approved metadata names and types before saving a review.
        from .reviewed_metadata import build_reviewed_analysis
        from .salesforce import api_name, object_api_name
        analysis = build_reviewed_analysis(plan)
        seen_objects = set()
        for module in analysis.modules:
            name = object_api_name(plan.repository_id, module.name).casefold()
            if name in seen_objects:
                raise ValueError(f"Colliding object API name: {name}")
            seen_objects.add(name)
            fields = set()
            for field in module.fields:
                key = (api_name(field.target.removesuffix("__c")) + "__c").casefold()
                if key in fields:
                    raise ValueError(f"Colliding field API name: {key}")
                fields.add(key)
                if field.data_type not in {"Text", "LongTextArea", "Number", "Checkbox", "Date", "DateTime", "Email"}:
                    raise ValueError(f"Unsupported Salesforce field type: {field.data_type}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    review.write_text(plan.model_dump_json(indent=2))
    return {"saved": True, "approved_entities": len(analysis.modules)}


def load_saved_review(project_id: str):
    """Load the server-saved review and recheck its source identity/evidence."""
    project, snapshot, review = project_paths(project_id)
    if not review.exists():
        raise HTTPException(409, "Canonical review required")
    plan = ReviewedCanonicalPlan.model_validate_json(review.read_text(encoding="utf-8"))
    ir = load_ir(snapshot)
    if (plan.repository_id != json.loads(project.read_text(encoding="utf-8")).get("repository_id")
            or plan.repository != ir.repository):
        raise HTTPException(409, "Repository identity changed")
    try:
        validate_plan_against_ir(plan, ir)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return plan


def reviewed_metadata_bundle(plan):
    """One shared ZIP implementation for browser export and local release jobs."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        export_reviewed_metadata(plan, root)
        (root / "canonical-review.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in root.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(root))
        return buffer.getvalue()


@router.get("/api/projects/{project_id}/canonical/metadata.zip")
def canonical_project_metadata(project_id: str):
    try:
        content = reviewed_metadata_bundle(load_saved_review(project_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(content), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="canonical-metadata.zip"'},
    )


@router.get("/api/projects/{project_id}/modules")
def module_candidates(project_id: str):
    """Preview logical modules from the project's existing evidence snapshot."""
    from .module_grouping import suggest_modules

    _, snapshot, _ = project_paths(project_id)
    return suggest_modules(load_ir(snapshot))


