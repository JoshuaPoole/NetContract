from pydantic import BaseModel, Field
from typing import Literal


class FieldMapping(BaseModel):
    source: str
    target: str
    data_type: str = "Text"
    external_id: bool = False
    pii: bool = False
    status: Literal["review", "approved", "rejected"] = "review"
    evidence: str = ""
    notes: str = ""


class Module(BaseModel):
    name: str
    source_file: str
    fields: list[FieldMapping] = Field(default_factory=list)


class Integration(BaseModel):
    source_file: str
    indicator: str
    confidence: Literal["declared", "inferred"] = "inferred"
    destination: str = "unknown"
    status: Literal["review", "approved", "rejected"] = "review"


class Analysis(BaseModel):
    repository: str
    repository_id: str = ""
    compatible: bool
    reasons: list[str]
    modules: list[Module]
    integrations: list[Integration]
    warnings: list[str] = Field(default_factory=list)

