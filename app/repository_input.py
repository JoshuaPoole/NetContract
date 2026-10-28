"""Canonical bounded repository input shared by ZIP and MCP adapters.

Static source is never executed. Provenance is retained independently of the
transport and is available to future scanners without reconstructing ZIPs.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath

from .discovery import (
    CONFIG_SUFFIXES, INFRA_NAMES, MAX_ENTRY_BYTES, MAX_FILES,
    MAX_TOTAL_UNCOMPRESSED, SKIP_PARTS, SOURCE_SUFFIXES,
)
from .container_discovery import is_dockerfile


@dataclass(frozen=True)
class RepositorySource:
    project: str
    revision: str
    transport: str


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    content: str


@dataclass(frozen=True)
class RepositoryInput:
    source: RepositorySource
    files: tuple[RepositoryFile, ...]

    def entries(self):
        return ((item.path, item.content) for item in self.files)


def accepted_path(value):
    if not isinstance(value, str) or not value or chr(0) in value or chr(92) in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(part in SKIP_PARTS for part in path.parts):
        return False
    return (path.suffix.lower() in SOURCE_SUFFIXES | CONFIG_SUFFIXES
            or path.name.lower() in INFRA_NAMES or is_dockerfile(value))


def repository_input(source: RepositorySource, entries) -> RepositoryInput:
    """Validate files and total bytes before any downstream analysis."""
    files = []
    seen = set()
    total = 0
    for path, content in entries:
        if not accepted_path(path):
            continue
        if path in seen:
            raise ValueError("Duplicate repository path")
        seen.add(path)
        if not isinstance(content, str):
            raise ValueError("Repository content must be decoded text")
        size = len(content.encode("utf-8"))
        if size > MAX_ENTRY_BYTES:
            continue
        total += size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise ValueError("Repository input exceeds safe scan budget")
        files.append(RepositoryFile(path, content))
        if len(files) > MAX_FILES:
            raise ValueError("Repository input has too many files")
    return RepositoryInput(source=source, files=tuple(files))
