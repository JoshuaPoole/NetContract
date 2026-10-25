"""Static, non-executing Python source scanner. All mappings are proposals."""

import ast
import re
import zipfile
from pathlib import Path
from .models import Analysis, Module, FieldMapping, Integration

MAX_FILES = 800
MAX_BYTES = 20_000_000
MAX_FILE_BYTES = 300_000
SKIP_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
}
SENSITIVE = re.compile(
    r"(email|phone|address|birth|password|token|secret|ssn|ip_address|principal|user_id|device_id)",
    re.I,
)
INTEGRATIONS = re.compile(
    r"(requests\.|httpx\.|fetch\(|axios\.|webhook|kafka|pubsub|salesforce|mongodb|boto3|sqlalchemy|mysql|postgres)",
    re.I,
)
TYPES = {
    "str": "Text",
    "int": "Number",
    "float": "Number",
    "bool": "Checkbox",
    "datetime": "DateTime",
    "date": "Date",
    "Decimal": "Number",
}


def safe_sources(archive: Path):
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError("Archive exceeds 20 MB safety limit")
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError("Too many archive entries")
        for info in infos:
            path = Path(info.filename)
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or any(x in SKIP_PARTS for x in path.parts)
            ):
                continue
            if (
                path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}
                or info.file_size > MAX_FILE_BYTES
            ):
                continue
            if info.compress_size and info.file_size / info.compress_size > 100:
                continue
            try:
                yield info.filename, z.read(info).decode("utf-8", errors="replace")
            except (RuntimeError, ValueError):
                continue


def extract_python_models(filename: str, source: str):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [ast.unparse(base) for base in node.bases]
        if not any(
            any(tag in b for tag in ("BaseModel", "SQLModel", "DeclarativeBase"))
            for b in bases
        ) and not any("models.Model" in b for b in bases):
            continue
        fields = []
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                name = child.target.id
                annotation = ast.unparse(child.annotation)
                fields.append(
                    FieldMapping(
                        source=f"{node.name}.{name}",
                        target=f"{name.title().replace('_','_')}__c",
                        data_type=next(
                            (v for k, v in TYPES.items() if k in annotation), "Text"
                        ),
                        pii=bool(SENSITIVE.search(name)),
                        evidence=f"{filename}:{child.lineno}",
                    )
                )
            elif (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
            ):
                name = child.targets[0].id
                if isinstance(child.value, ast.Call) and any(
                    x in ast.unparse(child.value.func)
                    for x in ("Column", "mapped_column")
                ):
                    fields.append(
                        FieldMapping(
                            source=f"{node.name}.{name}",
                            target=f"{name.title().replace('_','_')}__c",
                            pii=bool(SENSITIVE.search(name)),
                            evidence=f"{filename}:{child.lineno}",
                        )
                    )
        if fields:
            result.append(Module(name=node.name, source_file=filename, fields=fields))
    return result


def scan_archive(archive: Path) -> Analysis:
    modules, integrations, warnings = [], [], []
    source_count = 0
    for filename, source in safe_sources(archive):
        source_count += 1
        if filename.endswith(".py"):
            modules.extend(extract_python_models(filename, source))
        for idx, line in enumerate(source.splitlines(), 1):
            if INTEGRATIONS.search(line) and not line.lstrip().startswith("#"):
                integrations.append(
                    Integration(
                        source_file=f"{filename}:{idx}",
                        indicator=INTEGRATIONS.search(line).group(0),
                    )
                )
                if len(integrations) >= 100:
                    break
    if not modules:
        warnings.append(
            "No supported annotated Python models found; inspect manually or extend parsers"
        )
    warnings.append(
        "Static analysis cannot prove runtime data flows, source-of-truth ownership, or retention law"
    )
    return Analysis(
        repository=archive.name,
        compatible=bool(modules),
        reasons=[
            f"Analysed {source_count} supported source files",
            f"Found {len(modules)} candidate business models",
        ],
        modules=modules[:150],
        integrations=integrations[:100],
        warnings=warnings,
    )

