"""Bounded structural evidence for JSON policy and remediation records.

This inventory is descriptive: it never treats fixture values as executable
policies or infers approvals from arbitrary key names.
"""
import json
from pathlib import Path

from .discovery import _read_entries
from .readme_guidance import discover_readme_guidance

MAX_RECORDS = 20
MAX_DEPTH = 4
MAX_FIELDS = 40
MAX_FILES = 60
SENSITIVE_KEYS = ("password", "secret", "token", "credential", "api_key", "private_key")


def _shape(value, depth=0):
    if depth >= MAX_DEPTH:
        return {"type": type(value).__name__, "truncated": True}
    if isinstance(value, dict):
        keys = list(value)[:MAX_FIELDS]
        return {
            "type": "object",
            "fields": {str(key): _shape(value[key], depth + 1) for key in keys
                       if not any(word in str(key).lower() for word in SENSITIVE_KEYS)},
            "field_count": len(value),
            "truncated": len(value) > MAX_FIELDS,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "record_count": len(value),
            "item_shapes": [_shape(item, depth + 1) for item in value[:MAX_RECORDS]],
            "truncated": len(value) > MAX_RECORDS,
        }
    return {"type": "null" if value is None else type(value).__name__}


def inspect_structured_contracts(archive: Path) -> dict:
    """Inventory JSON shapes with file evidence; no data values are returned."""
    archive = Path(archive)
    guidance = discover_readme_guidance(archive)
    targets = {item["source_file"] for item in guidance["candidate_targets"]}
    results = []
    for filename, source in _read_entries(archive):
        if not filename.lower().endswith(".json"):
            continue
        if len(results) >= MAX_FILES:
            break
        try:
            value = json.loads(source)
        except (ValueError, UnicodeError):
            continue
        results.append({
            "source_file": filename,
            "readme_target": filename in targets,
            "structure": _shape(value),
            "review_status": "review",
        })
    results.sort(key=lambda x: (not x["readme_target"], x["source_file"]))
    return {
        "schema_version": "1.0",
        "source_repository": archive.name,
        "files": results,
        "warnings": [
            "Only JSON structure and types are shown; no source data values are returned.",
            "Record shapes are samples, not guarantees about all data.",
            "Fixtures, test data and production policies must be distinguished by review.",
            "No execution, approval, deployment or deletion is authorized.",
        ],
    }

