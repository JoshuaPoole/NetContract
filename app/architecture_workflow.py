"""Deterministic, review-gated architecture workflow for every ingestion source.

Agents may produce proposals but cannot advance or export a project themselves.
This model intentionally does not execute ETLs, DIPs, or Salesforce deployment.
"""
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class Stage(str, Enum):
    DISCOVER = "discover"
    CLASSIFY = "classify"
    NORMALISE = "normalise"
    CONTRACTS = "contracts"
    JOINS = "joins"
    DIPS = "dips"
    VALIDATE = "validate"
    APPROVE = "approve"
    GENERATE = "generate"


ORDER = tuple(Stage)


class Evidence(BaseModel):
    source_file: str
    reference: str


class StageDecision(BaseModel):
    stage: Stage
    evidence: list[Evidence] = Field(default_factory=list)
    proposal: dict = Field(default_factory=dict)
    validated: bool = False
    approved_by: str | None = None

    @model_validator(mode="after")
    def enforce_review(self):
        if self.stage == Stage.APPROVE and not self.approved_by:
            raise ValueError("Approval requires an identified reviewer")
        if self.stage not in (Stage.DISCOVER, Stage.CLASSIFY) and not self.evidence:
            raise ValueError("Stage requires source evidence")
        return self


class ArchitectureWorkflow(BaseModel):
    source_kind: str
    source_digest: str
    decisions: list[StageDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_order(self):
        if self.source_kind not in {"repository", "spreadsheet", "api", "configuration"}:
            raise ValueError("Unsupported ingestion source")
        if not self.source_digest:
            raise ValueError("Source digest is required")
        for index, decision in enumerate(self.decisions):
            if index >= len(ORDER) or decision.stage != ORDER[index]:
                raise ValueError("Architecture stages cannot be skipped or reordered")
            if index and not self.decisions[index - 1].validated:
                raise ValueError("Previous stage must be validated before advancing")
            if decision.stage == Stage.GENERATE and (
                not self.decisions[ORDER.index(Stage.APPROVE)].approved_by
                or not self.decisions[ORDER.index(Stage.APPROVE)].validated
            ):
                raise ValueError("Generation requires validated human approval")
        return self

    @property
    def next_stage(self) -> Stage | None:
        return ORDER[len(self.decisions)] if len(self.decisions) < len(ORDER) else None

