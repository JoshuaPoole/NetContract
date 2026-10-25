"""Typed, evidence-backed intermediate representation for review-only conversion.

Nodes and field candidates are observations, not proof of runtime data flow.
No speculative edges are created from shared filenames or matching identifiers.
"""
from pathlib import Path

from pydantic import BaseModel, Field

from .container_discovery import ContainerDefinition, ContainerStage
from .discovery import discover_repository
from .scanner import scan_archive, SENSITIVE
from .discovery import _read_entries
from .procedure_catalog import read_procedure_catalogs
from .salesforce import api_name


class Evidence(BaseModel):
    source_file: str
    line: int | None = None
    kind: str = "static"
    reference: str | None = None


def evidence_reference(evidence):
    if evidence.reference is not None:
        return evidence.source_file + '#' + evidence.reference
    return f"{evidence.source_file}:{evidence.line or 1}"


class IRField(BaseModel):
    source: str
    proposed_target: str
    proposed_type: str
    pii_candidate: bool = False
    status: str = "review"
    evidence: Evidence


class IRNode(BaseModel):
    id: str
    kind: str
    name: str
    evidence: Evidence
    fields: list[IRField] = Field(default_factory=list)
    persistence_operation: str | None = None
    entity_hint: str | None = None
    entity_evidence: str | None = None
    container_stage: ContainerStage | None = None


class IREdge(BaseModel):
    source_id: str
    target_id: str
    relation: str
    evidence: Evidence
    status: str = "candidate"


class RepositoryIR(BaseModel):
    schema_version: str = "1.0"
    repository: str
    static_only: bool = True
    nodes: list[IRNode] = Field(default_factory=list)
    edges: list[IREdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    container_definitions: list[ContainerDefinition] = Field(default_factory=list)
    procedure_catalogs: list[dict] = Field(default_factory=list)


def build_repository_ir(archive: Path) -> RepositoryIR:
    """Read the same bounded ZIP with existing static scanners; no code execution."""
    manifest = discover_repository(archive)
    analysis = scan_archive(archive)
    nodes = []
    for index, module in enumerate(analysis.modules):
        fields = []
        for field in module.fields:
            location, _, line = field.evidence.rpartition(":")
            fields.append(IRField(
                source=field.source,
                proposed_target=field.target,
                proposed_type=field.data_type,
                pii_candidate=field.pii,
                evidence=Evidence(source_file=location or module.source_file,
                                  line=int(line) if line.isdigit() else None),
            ))
        nodes.append(IRNode(
            id=f"model:{index}",
            kind="model_candidate",
            name=module.name,
            evidence=Evidence(source_file=module.source_file),
            fields=fields,
        ))
    catalogs, procedure_warnings = read_procedure_catalogs(_read_entries(archive))
    for catalog in catalogs:
        nodes.append(IRNode(
            id='procedure:' + catalog['name'], kind='model_candidate', name=catalog['name'],
            evidence=Evidence(source_file=catalog['source_file'], kind='json_catalog', reference=''),
            fields=[IRField(source=catalog['name'] + '.' + field['key'],
                            proposed_target=api_name(field['key'].title()) + '__c',
                            proposed_type=field['type'], pii_candidate=bool(SENSITIVE.search(field['key'])),
                            evidence=Evidence(source_file=catalog['source_file'], kind='json_catalog', reference=field['reference']))
                    for field in catalog['fields']],
        ))
    for index, endpoint in enumerate(manifest.get("api_endpoints", [])):
        nodes.append(IRNode(
            id=f"endpoint:{index}",
            kind="api_endpoint",
            name=endpoint.get("decorator", endpoint.get("function", "unknown")),
            evidence=Evidence(source_file=endpoint["source_file"], line=endpoint.get("line")),
        ))
    for index, operation in enumerate(manifest.get("persistence_operations", [])):
        nodes.append(IRNode(
            id=f"persistence:{index}",
            kind="persistence_candidate",
            name=operation.get("expression", operation.get("operation", "unknown")),
            evidence=Evidence(source_file=operation["source_file"], line=operation.get("line")),
            persistence_operation=operation.get("operation"),
            entity_hint=operation.get("entity_hint"),
            entity_evidence=operation.get("entity_evidence"),
        ))
    containers = [ContainerDefinition.model_validate(item) for item in manifest.get("container_definitions", [])]
    for definition_index, definition in enumerate(containers):
        for stage in definition.stages:
            nodes.append(IRNode(
                id=f"container:{definition_index}:{stage.index}", kind="container_image_candidate",
                name=f"Container stage {stage.alias or stage.index}: {stage.base_image or 'unresolved base'}",
                evidence=Evidence(source_file=definition.source_file, line=stage.from_line),
                container_stage=stage,
            ))
    return RepositoryIR(
        repository=manifest["repository"],
        nodes=nodes,
        container_definitions=containers,
        procedure_catalogs=catalogs,
        # Filename proximity, function names and heuristic operations are not
        # sufficient to assert an actual frontend -> backend -> database edge.
        edges=[],
        warnings=list(dict.fromkeys(
            analysis.warnings + manifest["warnings"] + procedure_warnings + [
                "No runtime lineage is asserted; candidate nodes need human verification",
                "Salesforce field mappings remain unapproved until explicitly reviewed",
            ]
        )),
    )



