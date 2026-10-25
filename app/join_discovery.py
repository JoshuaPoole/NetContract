"""Evidence-backed, read-only cross-source join proposals.

Only proposes joins across distinct sources. Never executes joins or reads row values.
"""
import re
from pydantic import BaseModel, Field
from .spreadsheet_discovery import SpreadsheetDiscovery


class SourceSchema(BaseModel):
    source_name: str
    discovery: SpreadsheetDiscovery


class ProposedJoin(BaseModel):
    left_source: str
    left_field: str
    right_source: str
    right_field: str
    evidence: list[str]
    confidence: str
    cardinality: str
    requires_review: bool = True


class JoinReview(BaseModel):
    proposals: list[ProposedJoin] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _key(name: str) -> bool:
    return name.lower().endswith(("_id", " id")) or _normalized(name) in {
        "id", "accountid", "customerid", "deviceid", "interfaceid", "invoiceid",
        "contractid", "supplierid", "incidentid", "orderid",
    }


def propose_joins(sources: list[SourceSchema]) -> JoinReview:
    if len(sources) < 2:
        return JoinReview(warnings=["At least two source schemas are needed to propose joins."])
    names = [s.source_name for s in sources]
    if any(not name.strip() for name in names) or len(names) != len(set(names)):
        raise ValueError("Source names must be nonempty and unique")
    proposals = []
    for index, left in enumerate(sources):
        for right in sources[index + 1:]:
            for a in left.discovery.columns:
                for b in right.discovery.columns:
                    if not _key(a.name) or _normalized(a.name) != _normalized(b.name):
                        continue
                    if a.inferred_type != b.inferred_type or a.inferred_type == "unknown":
                        continue
                    # Sample uniqueness is not a verified primary key or FK.
                    cardinality = (
                        "candidate_one_to_one" if a.unique and b.unique
                        else "candidate_one_to_many" if a.unique != b.unique
                        else "unknown"
                    )
                    proposals.append(ProposedJoin(
                        left_source=left.source_name, left_field=a.name,
                        right_source=right.source_name, right_field=b.name,
                        evidence=[f"{left.source_name}: {a.evidence}",
                                  f"{right.source_name}: {b.evidence}"],
                        confidence="low",
                        cardinality=cardinality,
                    ))
    return JoinReview(proposals=proposals, warnings=[
        "Matches are header/type heuristics, not validated foreign keys.",
        "Cardinality is only a sample-based candidate; confirm using authorised source data.",
        "No join is approved or executed automatically.",
    ])

