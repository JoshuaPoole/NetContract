"""Small, review-only logical grouping demo for existing repository observations."""
import re

from .intermediate_representation import RepositoryIR

MODULES = {
    "dip": "DIP management",
    "incident": "Incident management",
    "infrastructure": "Infrastructure",
    "unassigned": "Unassigned / needs context",
}


def suggest_modules(ir: RepositoryIR) -> dict:
    """Group across folders using explicit name/path hints, never infer ownership."""
    groups = {}
    for node in ir.nodes:
        # Split CamelCase as well as path separators; avoid matching 'dip' in words.
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", node.name + " " + node.evidence.source_file)
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        hints = []
        if tokens & {"dip", "dips", "actionplan"} or {"action", "plan"} <= tokens:
            hints.append("dip")
        if tokens & {"incident", "incidents"}:
            hints.append("incident")
        if node.kind == "container_image_candidate" or tokens & {"infra", "infrastructure", "terraform", "kubernetes", "deployment"}:
            hints.append("infrastructure")
        if node.kind == "container_image_candidate":
            hints = ["infrastructure"]
        key = hints[0] if len(hints) == 1 else "unassigned"
        group = groups.setdefault(key, {
            "id": key, "name": MODULES[key], "parent_id": "application",
            "status": "suggested", "elements": [],
        })
        group["elements"].append({
            "node_id": node.id, "name": node.name, "kind": node.kind,
            "source_file": node.evidence.source_file,
            "line": node.evidence.line,
            "field_count": len(node.fields),
            "reason": "Dockerfile stage evidence" if node.kind == "container_image_candidate"
            else "Name/path hint: " + hints[0] if len(hints) == 1
            else "Conflicting hints; needs review" if hints else "No supported module hint",
        })
    return {
        "application": ir.repository,
        "modules": [groups[key] for key in MODULES if key in groups],
        "warnings": [
            "Suggested logical containment only; names and paths do not prove ownership or data flow.",
            "Only discovered IR elements are included; infrastructure files without IR nodes are not inventoried.",
            "Business context, shared dependencies and module corrections require human review. No approval is changed.",
        ],
    }

