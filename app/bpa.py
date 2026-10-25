"""Domain-agnostic, review-only Business Process Automation (BPA) definitions.

A networking DIP is a specialised BPA, not the generic orchestration primitive.
No workflows are executed by this module.
"""
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class BPAKind(str, Enum):
    GENERIC = "generic"
    NETWORK_DIP = "network_dip"


class StepKind(str, Enum):
    VALIDATE = "validate"
    REVIEW = "review"
    APPROVE = "approve"
    PLAN = "plan"
    VERIFY = "verify"


class WorkflowStep(BaseModel):
    step_id: str = Field(min_length=1)
    kind: StepKind
    depends_on: list[str] = Field(default_factory=list)
    requires_human: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class BPADefinition(BaseModel):
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    kind: BPAKind = BPAKind.GENERIC
    source_contract_refs: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(min_length=1)
    approved: bool = False

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow step IDs must be unique")
        known = set(ids)
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError("Workflow steps cannot depend on themselves")
            if len(step.depends_on) != len(set(step.depends_on)):
                raise ValueError("Duplicate dependencies are not allowed")
            if any(dep not in known for dep in step.depends_on):
                raise ValueError("Workflow dependencies must reference existing steps")
        graph = {step.step_id: step.depends_on for step in self.steps}
        visited, visiting = set(), set()

        def walk(node):
            if node in visiting:
                raise ValueError("Workflow dependencies must not contain cycles")
            if node in visited:
                return
            visiting.add(node)
            for dep in graph[node]:
                walk(dep)
            visiting.remove(node)
            visited.add(node)

        for node in ids:
            walk(node)
        if self.kind == BPAKind.NETWORK_DIP:
            if self.domain != "network":
                raise ValueError("Network DIPs must belong to the network domain")
            kinds = {step.kind for step in self.steps}
            if not {StepKind.VALIDATE, StepKind.APPROVE, StepKind.VERIFY}.issubset(kinds):
                raise ValueError("Network DIPs require validation, approval and verification steps")
            if not any(step.kind == StepKind.APPROVE and step.requires_human for step in self.steps):
                raise ValueError("Network DIPs require a human approval gate")
        if self.approved:
            raise ValueError("Workflow approval cannot be asserted by client-supplied definitions")
        return self


class BPAReview(BaseModel):
    definition: BPADefinition
    execution_enabled: bool = False
    warnings: list[str] = Field(default_factory=lambda: [
        "Definition only: no work orders, execution or device changes are performed.",
        "Approval requires a separate server-owned, audited human decision.",
    ])


def review_bpa(definition: BPADefinition) -> BPAReview:
    return BPAReview(definition=definition)

