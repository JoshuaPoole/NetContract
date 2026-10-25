"""Read-only CSV discovery: source-backed headers, inferred types and candidate joins.

Never executes uploaded content, persists record values, or approves relationships.
"""
import csv
import hashlib
import io
from pydantic import BaseModel, Field

MAX_BYTES = 2_000_000
MAX_ROWS = 10_000
MAX_COLUMNS = 200


class ColumnContract(BaseModel):
    name: str
    inferred_type: str
    nullable: bool
    unique: bool
    evidence: str
    pii_candidate: bool = False


class JoinCandidate(BaseModel):
    left_column: str
    right_column: str
    reason: str
    confidence: str = "low"
    requires_review: bool = True


class SpreadsheetDiscovery(BaseModel):
    source_digest: str
    row_count: int
    columns: list[ColumnContract] = Field(default_factory=list)
    join_candidates: list[JoinCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _type(values: list[str]) -> str:
    present = [v.strip() for v in values if v.strip()]
    if not present:
        return "unknown"
    if all(v.lower() in {"true", "false"} for v in present):
        return "boolean"
    try:
        for v in present:
            int(v)
        return "integer"
    except ValueError:
        pass
    try:
        for v in present:
            float(v)
        return "number"
    except ValueError:
        return "text"


def discover_csv(data: bytes) -> SpreadsheetDiscovery:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("CSV must be nonempty and at most 2 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader)
        if not headers or len(headers) > MAX_COLUMNS:
            raise ValueError("CSV must contain 1-200 columns")
        if any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV headers must be nonempty and unique")
        values = [[] for _ in headers]
        row_count = 0
        for row in reader:
            if len(row) != len(headers):
                raise ValueError("CSV row has an unexpected number of columns")
            row_count += 1
            if row_count > MAX_ROWS:
                raise ValueError("CSV exceeds 10,000 rows")
            for index, value in enumerate(row):
                values[index].append(value)
    except (csv.Error, StopIteration) as exc:
        raise ValueError("Malformed or empty CSV") from exc

    columns = []
    for name, entries in zip(headers, values):
        present = [v for v in entries if v.strip()]
        label = name.lower().replace("-", "_").replace(" ", "_")
        pii = any(term in label for term in ("email", "phone", "address", "birth", "ssn", "tax_file"))
        columns.append(ColumnContract(
            name=name, inferred_type=_type(entries),
            nullable=len(present) != row_count,
            unique=len(present) == len(set(present)),
            evidence=f"CSV header: {name}; inspected {row_count} rows",
            pii_candidate=pii,
        ))
    # A single table cannot establish foreign-key joins. Avoid fabricated joins.
    return SpreadsheetDiscovery(
        source_digest=hashlib.sha256(data).hexdigest(),
        row_count=row_count,
        columns=columns,
        warnings=["Types are heuristic; no joins or mappings are approved.",
                  "Potential PII classification requires human review.",
                  "Source record values are not included in the discovery response."],
    )

