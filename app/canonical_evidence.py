"""Verify reviewed canonical plans against a server-saved repository scan.

Client-supplied evidence strings are not proof. Match source identifiers, source
locations, entity concepts and proposed types to the original immutable scan.
"""
from .canonical_entities import group_canonical_entities
from .contract_classification import classify_models
from .procedure_catalog import IDENTITIES
from .intermediate_representation import evidence_reference, RepositoryIR
from .reviewed_metadata import ReviewedCanonicalPlan


def validate_plan_against_ir(plan: ReviewedCanonicalPlan, ir: RepositoryIR) -> None:
    candidates = {item.concept: item for item in group_canonical_entities(classify_models(ir))}
    nodes = {(node.name, node.evidence.source_file): node for node in ir.nodes
             if node.kind == "model_candidate"}
    used_sources = set()
    for entity in plan.entities:
        if entity.status != "approved":
            continue
        candidate = candidates.get(entity.concept)
        if candidate is None:
            raise ValueError(f"Unknown canonical concept: {entity.concept}")
        allowed_evidence = {evidence for item in candidate.representations for evidence in item.evidence}
        if not entity.evidence or not set(entity.evidence).issubset(allowed_evidence):
            raise ValueError(f"Unverified entity evidence: {entity.concept}")
        allowed = {(item.name, item.source_file) for item in candidate.representations}
        matching = [key for key in allowed if key[0] in entity.source_representations]
        if not matching or set(entity.source_representations) != {key[0] for key in matching}:
            raise ValueError(f"Unverified source representations: {entity.concept}")
        for field in entity.fields:
            if field.status != "approved":
                continue
            matches = [(node, source_field) for key in matching
                       for node in [nodes.get(key)] if node is not None
                       for source_field in node.fields if source_field.source == field.source]
            if len(matches) != 1:
                raise ValueError(f"Unknown or ambiguous source field: {field.source}")
            _node, source_field = matches[0]
            source_location = evidence_reference(source_field.evidence)
            if field.evidence != source_location:
                raise ValueError(f"Unverified field evidence: {field.source}")
            if field.data_type != source_field.proposed_type:
                raise ValueError(f"Field type differs from scan; explicit mapping review required: {field.source}")
            if field.external_id and (entity.concept != 'DIP' or field.data_type != 'Text'
                    or field.source.rsplit('.', 1)[-1] not in IDENTITIES
                    or source_field.evidence.kind != 'json_catalog'):
                raise ValueError('External IDs require a reviewed text procedure identity from a catalog')
            if field.pii_candidate != source_field.pii_candidate:
                raise ValueError(f"Privacy signal differs from scan: {field.source}")
            if field.source in used_sources:
                raise ValueError(f"Source field approved twice: {field.source}")
            used_sources.add(field.source)



