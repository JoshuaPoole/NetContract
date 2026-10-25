"""Offline regression tests for review-only canonical entity grouping."""
from app.canonical_entities import group_canonical_entities
from app.contract_classification import ClassifiedModel


def candidate(name, role="business_entity_candidate", persistence="unverified"):
    return ClassifiedModel(name=name, source_file=f"src/{name}.py",
                           role=role, persistence=persistence)


def test_incident_representations_group_without_approval():
    models = [candidate("IncomingIncident"), candidate("HistoricalIncident"),
              candidate("WorkflowIncident"), candidate("MCPIncidentPayload",
                  role="api_or_integration_contract")]
    groups = group_canonical_entities(models)
    assert len(groups) == 1
    assert groups[0].concept == "Incident"
    assert len(groups[0].representations) == 3
    assert groups[0].status == "review"
    assert groups[0].proposed_salesforce_object is None


def test_processing_and_api_models_do_not_create_entities():
    assert group_canonical_entities([
        candidate("PipelineJob", role="processing_model"),
        candidate("MCPToolResponse", role="api_or_integration_contract"),
    ]) == []


def test_persistence_hint_remains_unverified_for_storage_approval():
    groups = group_canonical_entities([
        candidate("IncomingIncident", persistence="candidate_operation_evidence")
    ])
    assert groups[0].persistence == "candidate_operation_evidence"
    assert groups[0].status == "review"
    assert groups[0].proposed_salesforce_object is None


def test_distinct_business_concepts_stay_separate():
    groups = group_canonical_entities([
        candidate("ActionPlan"), candidate("ApprovalRule"),
        candidate("ExecutionStatus"), candidate("IncomingIncident")
    ])
    assert {group.concept for group in groups} == {
        "ActionPlan", "Approval", "ExecutionStatus", "Incident"
    }

