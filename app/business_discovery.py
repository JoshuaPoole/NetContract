"""Review-only business contract candidates correlated to source evidence.

README is a navigation hint. A contract candidate requires a matching source
symbol or structured JSON key; it is not a verified runtime business contract.
"""
import ast
import hashlib
import json
from pathlib import Path

from .business_contracts import ApplicationBlueprint, BusinessContract, SourceEvidence
from .discovery import _read_entries
from .procedure_catalog import is_procedure_name
from .readme_guidance import BUSINESS_TERMS, discover_readme_guidance

MAX_CONTRACTS = 100
MAX_SYMBOLS_PER_FILE = 100
KIND_ORDER = ("incident", "dip", "execution_policy", "approval_rule", "workflow")


def _kind_for_symbol(symbol: str) -> str | None:
    normalized = symbol.lower().replace("-", "_")
    if is_procedure_name(symbol):
        return "dip"
    for kind in KIND_ORDER:
        if any(term in normalized for term in (BUSINESS_TERMS[kind] + (("approve", "authorize") if kind == "approval_rule" else ()))):
            return kind
    return None


def _symbols(filename: str, content: str):
    """Extract named declarations or top-level JSON keys without executing code."""
    if filename.lower().endswith(".py"):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        return [(node.name, node.lineno) for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))][:MAX_SYMBOLS_PER_FILE]
    if filename.lower().endswith(".json"):
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            return []
        if isinstance(value, dict):
            return [(str(key), 1) for key in list(value)[:MAX_SYMBOLS_PER_FILE]]
        if isinstance(value, list):
            keys = set()
            for record in value[:20]:
                if isinstance(record, dict):
                    keys.update(str(key) for key in record)
            return [(key, 1) for key in sorted(keys)[:MAX_SYMBOLS_PER_FILE]]
    return []


def discover_business_candidates(archive: Path) -> dict:
    """Return unapproved candidate blueprint and traceable source references."""
    archive = Path(archive)
    guidance = discover_readme_guidance(archive)
    targets = {item["source_file"]: item for item in guidance["candidate_targets"]}
    entries = dict(_read_entries(archive))
    contracts = []
    for filename in sorted(entries):
        if len(contracts) >= MAX_CONTRACTS:
            break
        if not filename.lower().endswith((".py", ".json")):
            continue
        for symbol, line in _symbols(filename, entries[filename]):
            kind = _kind_for_symbol(symbol)
            if kind is None:
                continue
            digest = hashlib.sha256(f"{filename}:{symbol}:{line}".encode()).hexdigest()[:12]
            contracts.append(BusinessContract(
                contract_id=f"candidate-{digest}",
                kind=kind,
                name=symbol,
                evidence=[SourceEvidence(source_file=filename, reference=f"symbol:{symbol}:line:{line}")],
            ))
            if len(contracts) >= MAX_CONTRACTS:
                break
    contracts.sort(key=lambda item: (
        item.evidence[0].source_file not in targets,
        KIND_ORDER.index(item.kind), item.evidence[0].source_file, item.name
    ))
    blueprint = ApplicationBlueprint(source_repository=archive.name, business_contracts=contracts)
    return {
        "blueprint": blueprint.model_dump(),
        "readme_guidance": guidance,
        "candidate_count": len(contracts),
        "warnings": [
            "Symbol and JSON-key matches are review-only candidates, not verified business contracts.",
            "README guidance changes inspection priority only; it cannot approve candidates.",
            "JavaScript/TypeScript semantics, nested policy values and cross-file behavior are not yet verified.",
            "No Salesforce metadata, Flow, permissions, execution or deletion is generated.",
        ],
    }


