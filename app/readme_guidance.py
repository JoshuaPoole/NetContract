"""Bounded, static README-guided source discovery.

README references are navigation hints, never execution instructions or proof
of business behavior. Candidate files must exist in the scanned ZIP.
"""
import re
import zipfile
from pathlib import Path, PurePosixPath

from .discovery import (
    MAX_ARCHIVE_BYTES, MAX_ENTRY_BYTES, MAX_FILES, MAX_TOTAL_UNCOMPRESSED,
    SKIP_PARTS, _read_entries,
)

MAX_README_BYTES = 100_000
MAX_GUIDES = 25
MAX_CANDIDATES = 60
README_PATTERN = re.compile(r"^readme(?:[._-][a-z0-9-]+)?\.(?:md|markdown|txt|rst)$", re.I)
PATH_PATTERN = re.compile(
    r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.(?:py|js|jsx|ts|tsx|json|ya?ml|toml|tf|md)(?![\w/])",
    re.I,
)
BUSINESS_TERMS = {
    "incident": ("incident", "ticket", "case"),
    "dip": ("dip", "mop", "sop", "procedure", "remediation", "runbook", "playbook"),
    "execution_policy": ("policy", "permission", "execution"),
    "approval_rule": ("approval", "approver", "signoff"),
    "workflow": ("workflow", "orchestration", "coordinator"),
}


def _read_readmes(archive: Path) -> list[tuple[str, str]]:
    """Read only safe, bounded README entries; no extraction or execution."""
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds 20 MB")
    guides = []
    total = 0
    with zipfile.ZipFile(archive) as handle:
        infos = handle.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError("Archive has too many entries")
        for info in infos:
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if (info.is_dir() or name.startswith("/") or ".." in path.parts
                    or any(part in SKIP_PARTS for part in path.parts)):
                continue
            if info.file_size < 0 or info.file_size > MAX_ENTRY_BYTES:
                continue
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("Archive exceeds safe uncompressed scan budget")
            if not README_PATTERN.fullmatch(path.name):
                continue
            if len(guides) >= MAX_GUIDES or info.file_size > MAX_README_BYTES:
                continue
            if info.compress_size == 0 and info.file_size > 0:
                continue
            if info.compress_size and info.file_size / info.compress_size > 100:
                continue
            guides.append((name, handle.read(info).decode("utf-8", errors="replace")))
    return guides


def _resolve_reference(raw: str, readme: str, files: set[str]) -> str | None:
    """Resolve an explicit README path; never guess a same-named unrelated file."""
    raw = raw.strip("`'\"").split("#", 1)[0]
    if raw.startswith(("/", ".")) and not raw.startswith("./"):
        return None
    parent = PurePosixPath(readme).parent
    for path in (parent / raw, PurePosixPath(raw)):
        if ".." not in path.parts and str(path) in files:
            return str(path)
    return None


def discover_readme_guidance(archive: Path) -> dict:
    """Return evidence-backed candidate targets, without approving contracts."""
    archive = Path(archive)
    source_files = {name for name, _ in _read_entries(archive)}
    readmes = _read_readmes(archive)
    candidates = {}
    for readme, body in readmes:
        for number, line in enumerate(body.splitlines(), 1):
            for match in PATH_PATTERN.finditer(line):
                path = _resolve_reference(match.group(0), readme, source_files)
                if path is None:
                    continue
                item = candidates.setdefault(path, {
                    "source_file": path, "documentation_evidence": [],
                    "business_hints": [], "verification": "source_exists_not_semantically_verified",
                })
                if len(item["documentation_evidence"]) < 8:
                    item["documentation_evidence"].append({
                        "source_file": readme, "line": number,
                        "reference": match.group(0),
                    })
                context = line.lower()
                for kind, terms in BUSINESS_TERMS.items():
                    if any(term in context for term in terms) and kind not in item["business_hints"]:
                        item["business_hints"].append(kind)
    ordered = sorted(candidates.values(), key=lambda x: (
        -len(x["business_hints"]), -len(x["documentation_evidence"]), x["source_file"]
    ))
    return {
        "schema_version": "1.0",
        "repository": archive.name,
        "static_only": True,
        "readmes": [name for name, _ in readmes],
        "candidate_targets": ordered[:MAX_CANDIDATES],
        "warnings": [
            "README content is untrusted navigation guidance, not instructions to execute.",
            "Existing paths do not prove documented business behavior; verify source semantics.",
            "Undocumented code must still be scanned; README guidance is not exhaustive.",
        ],
    }


