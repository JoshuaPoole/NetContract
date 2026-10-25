import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from .models import Analysis
from .intermediate_representation import RepositoryIR, build_repository_ir
from .ir_salesforce_bridge import ir_to_analysis
from .salesforce import api_name
from .salesforce import object_api_name
import hashlib
from .architecture_workflow import ArchitectureWorkflow, Stage, StageDecision, Evidence
from .spreadsheet_discovery import discover_csv
from .join_discovery import SourceSchema, JoinReview, propose_joins
from .bpa import BPADefinition, BPAReview, review_bpa
from .discovery_inventory import build_discovery_inventory

from .salesforce_browser import router as salesforce_browser_router
from .canonical_preview_api import router as canonical_preview_router
from .canonical_project_api import router as canonical_project_router

from .mim_incidents import router as mim_incidents_router

app = FastAPI(title="LifeAfterCode DevOps")
app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "assets"), name="assets")
app.include_router(canonical_preview_router)
app.include_router(canonical_project_router)
app.include_router(salesforce_browser_router)
app.include_router(mim_incidents_router)
DATA = Path(os.environ.get("MAPPER_WORKSPACE", "workspace"))
DATA.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def fresh_browser_assets(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/salesforce", "/mim"} or request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def load(project_id: str):
    if not project_id.isalnum():
        raise HTTPException(400, "Invalid ID")
    f = DATA / f"{project_id}.json"
    if not f.exists():
        raise HTTPException(404, "Project not found")
    return Analysis.model_validate_json(f.read_text())


@app.get("/", response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/salesforce", response_class=HTMLResponse)
def salesforce_review_page():
    return (Path(__file__).parent / "salesforce.html").read_text(encoding="utf-8")


def validate_deployment(analysis: Analysis):
    """Validate approved Salesforce metadata before deployment."""
    seen_objects = set()
    seen_fields = set()
    approved_count = 0

    for module in analysis.modules:
        approved = [field for field in module.fields if field.status == "approved"]

        if not approved:
            continue

        object_name = object_api_name(
            analysis.repository_id,
            module.name,
        )
        object_key = object_name.lower()

        if object_key in seen_objects:
            raise HTTPException(
                status_code=400, detail=f"Duplicate Salesforce object: {object_name}"
            )

        seen_objects.add(object_key)

        for field in approved:
            approved_count += 1

            field_name = api_name(field.target.removesuffix("__c")) + "__c"

            key = (object_key, field_name.lower())

            if key in seen_fields:
                raise HTTPException(
                    status_code=400, detail=f"Duplicate Salesforce field: {field_name}"
                )

            seen_fields.add(key)

            if field.data_type not in {
                "Text",
                "LongTextArea",
                "Number",
                "Checkbox",
                "Date",
                "DateTime",
                "Email",
            }:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported field type: {field.data_type}"
                )

    if approved_count == 0:
        raise HTTPException(
            status_code=400, detail="Approve at least one field before deployment."
        )

    return approved_count


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")

    data = await file.read(20_000_001)

    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")

    repository_id = hashlib.sha256(data).hexdigest()
    project_id = uuid.uuid4().hex

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "input.zip"
        path.write_bytes(data)

        try:
            ir = build_repository_ir(path)
            inventory = build_discovery_inventory(path)
            analysis = ir_to_analysis(ir)
            analysis.repository_id = repository_id
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc))

    (DATA / f"{project_id}.json").write_text(analysis.model_dump_json(indent=2))
    (DATA / f"{project_id}.ir.json").write_text(ir.model_dump_json(indent=2))
    (DATA / f"{project_id}.discovery.json").write_text(
        json.dumps(inventory), encoding="utf-8"
    )
    workflow = ArchitectureWorkflow(
        source_kind="repository", source_digest=repository_id,
        decisions=[StageDecision(
            stage=Stage.DISCOVER,
            evidence=[Evidence(source_file="uploaded-repository.zip", reference="sha256:" + repository_id)],
            proposal={"candidate_count": len(ir.nodes)},
            validated=True,
        )],
    )
    (DATA / f"{project_id}.workflow.json").write_text(workflow.model_dump_json(indent=2))

    return {"project_id": project_id, "analysis": analysis, "ir": ir.model_dump(),
            "inventory": inventory}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return load(project_id)


@app.get("/api/projects/{project_id}/discovery")
def get_discovery_inventory(project_id: str):
    analysis = load(project_id)
    snapshot = DATA / f"{project_id}.discovery.json"
    ir_snapshot = DATA / f"{project_id}.ir.json"
    if not snapshot.exists() or not ir_snapshot.exists():
        raise HTTPException(409, "Re-scan this repository to save its discovery inventory")
    return {"project_id": project_id, "analysis": analysis,
            "ir": RepositoryIR.model_validate_json(ir_snapshot.read_text(encoding="utf-8")).model_dump(),
            "inventory": json.loads(snapshot.read_text(encoding="utf-8"))}


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, analysis: Analysis):
    existing = load(project_id)
    if analysis.repository_id != existing.repository_id or analysis.repository != existing.repository:
        raise HTTPException(409, "Repository identity cannot be changed by review updates")
    (DATA / f"{project_id}.json").write_text(analysis.model_dump_json(indent=2))
    return {"saved": True}


@app.get("/api/projects/{project_id}/metadata.zip")
def metadata(project_id: str):
    """Legacy field-only metadata export is no longer permitted."""
    load(project_id)
    raise HTTPException(
        410, "Legacy field-only export retired; use project canonical review and metadata"
    )


@app.post("/api/projects/{project_id}/deploy")
def deploy_project(project_id: str):
    """Never deploy from unverified client-supplied legacy approvals."""
    load(project_id)
    raise HTTPException(
        403, "Automatic Salesforce deployment disabled; review and deploy offline metadata manually"
    )


@app.post("/api/ir/analyze")
async def analyze_ir(file: UploadFile = File(...)):
    """Preview evidence-backed repository IR; no approvals or deployments."""
    from .intermediate_representation import build_repository_ir

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        archive.write_bytes(data)
        try:
            ir = build_repository_ir(archive)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    return ir.model_dump()


@app.post("/api/guide/analyze")
async def analyze_readme_guidance(file: UploadFile = File(...)):
    """Preview README-guided source targets; never executes uploaded code."""
    from .readme_guidance import discover_readme_guidance

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        archive.write_bytes(data)
        try:
            guidance = discover_readme_guidance(archive)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    return guidance


@app.post("/api/business/analyze")
async def analyze_business_candidates(file: UploadFile = File(...)):
    """Preview source-backed business candidates; never approves or deploys."""
    from .business_discovery import discover_business_candidates

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        archive.write_bytes(data)
        try:
            result = discover_business_candidates(archive)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    return result


@app.post("/api/structured/analyze")
async def analyze_structured_contracts(file: UploadFile = File(...)):
    """Inspect nested JSON contract shapes without revealing record values."""
    from .structured_contracts import inspect_structured_contracts

    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        archive.write_bytes(data)
        try:
            result = inspect_structured_contracts(archive)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    return result


@app.post("/api/contracts/classify")
async def classify_contract_roles(file: UploadFile = File(...)):
    """Classify static model roles without proposing persistence or deployment."""
    from .contract_classification import classify_models
    from .canonical_entities import group_canonical_entities
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a ZIP archive")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000:
        raise HTTPException(413, "ZIP too large")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        archive.write_bytes(data)
        try:
            ir = build_repository_ir(archive)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
    classified = classify_models(ir)
    return {
        "models": [model.model_dump() for model in classified],
        "canonical_entities": [entity.model_dump() for entity in group_canonical_entities(classified)],
        "warnings": [
            "Classification is heuristic and review-only.",
            "Persistence is unverified for every model; no Salesforce object is approved.",
        ],
    }


@app.get("/api/projects/{project_id}/workflow")
def get_architecture_workflow(project_id: str):
    """Read the server-created ingestion workflow; never accept client-authored stages."""
    load(project_id)
    path = DATA / f"{project_id}.workflow.json"
    if not path.exists():
        raise HTTPException(404, "Workflow not found for this project")
    return ArchitectureWorkflow.model_validate_json(path.read_text())


@app.post("/api/spreadsheets/discover")
async def discover_spreadsheet(file: UploadFile = File(...)):
    """Read-only CSV contract discovery; no approval, storage or execution."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Upload a CSV file")
    data = await file.read(2_000_001)
    try:
        result = discover_csv(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    workflow = ArchitectureWorkflow(
        source_kind="spreadsheet", source_digest=result.source_digest,
        decisions=[StageDecision(
            stage=Stage.DISCOVER,
            evidence=[Evidence(source_file="uploaded.csv", reference="sha256:" + result.source_digest)],
            proposal={"columns": len(result.columns), "rows": result.row_count},
            validated=True,
        )],
    )
    return {"discovery": result.model_dump(), "workflow": workflow.model_dump()}


@app.post("/api/contracts/joins/propose", response_model=JoinReview)
def propose_contract_joins(sources: list[SourceSchema]):
    """Suggest review-only cross-source joins from previously discovered schemas."""
    if len(sources) > 20:
        raise HTTPException(400, "At most 20 sources may be compared")
    try:
        return propose_joins(sources)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/bpa/review", response_model=BPAReview)
def review_bpa_definition(definition: BPADefinition):
    """Validate a proposed generic BPA or networking DIP without execution."""
    return review_bpa(definition)


