"""Static Dockerfile inventory. Never builds images or runs repository commands.

Startup arguments, ENV/ARG values, RUN and healthcheck bodies are not returned.
This is an evidence inventory, not a complete Dockerfile evaluator.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import PurePosixPath

from pydantic import BaseModel, Field


class StartupHint(BaseModel):
    instruction: str
    line: int
    form: str
    executable: str | None = None


class ContainerStage(BaseModel):
    index: int
    alias: str | None = None
    base_image: str | None = None
    from_line: int
    default_target: bool = False
    exposed_ports: list[str] = Field(default_factory=list)
    entrypoint: StartupHint | None = None
    command: StartupHint | None = None
    healthcheck_declared: bool = False
    environment_names: list[str] = Field(default_factory=list)
    argument_names: list[str] = Field(default_factory=list)


class ContainerDefinition(BaseModel):
    source_file: str
    stages: list[ContainerStage] = Field(default_factory=list)
    global_argument_names: list[str] = Field(default_factory=list)
    runtime_status: str = "unverified"
    warnings: list[str] = Field(default_factory=list)


def is_dockerfile(filename: str) -> bool:
    name = PurePosixPath(filename).name.lower()
    return name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile")


def _instructions(source: str):
    """Join continuations and skip heredoc bodies rather than interpreting them."""
    escape = "\\"
    buffer = ""
    start = 0
    heredocs = []
    for number, raw in enumerate(source.splitlines(), 1):
        if heredocs:
            if raw.strip() == heredocs[0]:
                heredocs.pop(0)
            continue
        stripped = raw.strip()
        directive = re.fullmatch(r"#\s*escape\s*=\s*([`\\])", stripped, re.IGNORECASE)
        if directive and not buffer:
            escape = directive[1]
        if not stripped or stripped.startswith("#"):
            continue
        if not buffer:
            start = number
        continued = stripped.endswith(escape)
        buffer += stripped[:-1] + " " if continued else stripped
        if continued:
            continue
        match = re.match(r"([A-Za-z]+)\s+(.*)", buffer)
        if match:
            instruction, value = match[1].upper(), match[2]
            heredocs = re.findall(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", value)
            yield instruction, value, start, bool(heredocs)
        buffer = ""


def _startup(instruction: str, value: str, line: int) -> StartupHint:
    executable = None
    form = "shell"
    if value.startswith("["):
        form = "exec"
        try:
            tokens = json.loads(value)
            token = tokens[0] if isinstance(tokens, list) and tokens else None
        except ValueError:
            token = None
            form = "unparsed"
    else:
        token = value.split(maxsplit=1)[0] if value.strip() else None
    # Limit output to an executable/path, without command arguments or expansions.
    if isinstance(token, str) and not token.startswith("-") and re.fullmatch(r"[A-Za-z0-9_./-]+", token):
        executable = token
    return StartupHint(instruction=instruction, line=line, form=form, executable=executable)


def discover_container_definitions(entries: list[tuple[str, str]]) -> list[ContainerDefinition]:
    definitions = []
    for filename, source in entries:
        if not is_dockerfile(filename):
            continue
        definition = ContainerDefinition(source_file=filename, warnings=[
            "Declared image configuration only; no service or running container is confirmed.",
            "Build arguments, inherited image defaults, Compose overrides and entrypoint script contents are not resolved.",
        ])
        stage = None
        for instruction, value, line, heredoc in _instructions(source):
            if heredoc:
                definition.warnings.append(f"Heredoc body skipped at line {line}")
            if instruction == "FROM":
                tokens = value.split()
                tokens = [token for token in tokens if not token.startswith("--")]
                image = tokens[0] if tokens else None
                alias = tokens[2] if len(tokens) == 3 and tokens[1].lower() == "as" else None
                if image and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*(?:@sha256:[a-fA-F0-9]{64})?", image):
                    image = None
                    definition.warnings.append(f"Unresolved FROM expression at line {line}")
                if alias and not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
                    alias = None
                stage = ContainerStage(index=len(definition.stages), alias=alias, base_image=image, from_line=line)
                definition.stages.append(stage)
            elif stage is None:
                if instruction == "ARG":
                    name = value.split("=", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        definition.global_argument_names.append(name)
                continue
            elif instruction == "EXPOSE":
                for token in value.split():
                    match = re.fullmatch(r"([0-9]{1,5})(/(?:tcp|udp))?", token.lower())
                    if match and 1 <= int(match[1]) <= 65535:
                        port = match[1] + (match[2] or "/tcp")
                        if port not in stage.exposed_ports:
                            stage.exposed_ports.append(port)
                    else:
                        definition.warnings.append(f"Unresolved or unsupported EXPOSE expression at line {line}")
            elif instruction in {"ENTRYPOINT", "CMD"}:
                hint = _startup(instruction, "" if heredoc else value, line)
                if instruction == "ENTRYPOINT":
                    stage.entrypoint = hint
                else:
                    stage.command = hint
            elif instruction == "HEALTHCHECK":
                stage.healthcheck_declared = value.strip().upper() != "NONE"
            elif instruction in {"ARG", "ENV"}:
                # Parse quoting to avoid mistaking assignments inside a value for names.
                try:
                    parts = shlex.split(value)
                except ValueError:
                    parts = []
                    definition.warnings.append(f"Unparsed variable declaration at line {line}")
                if instruction == "ARG":
                    proposed = [parts[0].split("=", 1)[0]] if parts else []
                elif parts and "=" in parts[0]:
                    proposed = [part.split("=", 1)[0] for part in parts if "=" in part]
                else:
                    proposed = parts[:1]
                names = [name for name in proposed if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)]
                target = stage.argument_names if instruction == "ARG" else stage.environment_names
                target.extend(name for name in names if name not in target)
            elif instruction == "ONBUILD":
                definition.warnings.append(f"Deferred ONBUILD instruction not resolved at line {line}")
        if definition.stages:
            definition.stages[-1].default_target = True
        else:
            definition.warnings.append("No FROM stage parsed; manual review required")
        definition.warnings = list(dict.fromkeys(definition.warnings))
        definitions.append(definition)
    return definitions
