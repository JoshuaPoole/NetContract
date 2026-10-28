"""Read-only MCP repository snapshot adapter for the existing ZIP scanners.

The caller supplies a verified MCP tool invocation function; this module does
not read credentials, start processes, or grant access to arbitrary projects.
"""
import io
import zipfile
from pathlib import PurePosixPath

from .discovery import MAX_ARCHIVE_BYTES, MAX_ENTRY_BYTES, MAX_FILES, SKIP_PARTS


def _safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or chr(0) in value or chr(92) in value:
        raise ValueError("Invalid repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(part in SKIP_PARTS for part in path.parts):
        raise ValueError("Unsafe repository path")
    return str(path)


def repository_snapshot_zip(project_path: str, ref: str, list_tree, read_file) -> bytes:
    """Create a bounded scanner-compatible ZIP from trusted read-only MCP calls.

    list_tree(project_path, ref) must return a finite list of dicts with path/type.
    read_file(project_path, ref, path) must return UTF-8 text. Tool adapters must
    validate the authenticated project and resolve pagination before calling.
    """
    if not project_path or not ref or any(c in ref for c in "\r\n\\x00"):
        raise ValueError("Project and ref are required")
    entries = list_tree(project_path, ref)
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError("Repository tree exceeds safe scan budget")
    output = io.BytesIO()
    total = 0
    seen = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            try:
                path = _safe_path(entry.get("path"))
            except ValueError:
                continue
            if path in seen:
                raise ValueError("Duplicate repository path")
            seen.add(path)
            suffix = PurePosixPath(path).suffix.lower()
            name = PurePosixPath(path).name.lower()
            from .discovery import SOURCE_SUFFIXES, CONFIG_SUFFIXES, INFRA_NAMES
            from .container_discovery import is_dockerfile
            if suffix not in SOURCE_SUFFIXES | CONFIG_SUFFIXES and name not in INFRA_NAMES and not is_dockerfile(path):
                continue
            value = read_file(project_path, ref, path)
            if not isinstance(value, str):
                raise ValueError("MCP file adapter must return decoded text")
            data = value.encode("utf-8")
            if len(data) > MAX_ENTRY_BYTES:
                continue
            total += len(data)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("MCP snapshot exceeds safe scan budget")
            archive.writestr(path, data)
    if output.tell() > MAX_ARCHIVE_BYTES:
        raise ValueError("MCP snapshot ZIP exceeds upload limit")
    return output.getvalue()
