"""Read Terraform declarations without evaluating expressions or loading state."""
import json
import re
from pathlib import PurePosixPath

BLOCK_LABELS = {"resource": 2, "data": 2, "module": 1, "provider": 1,
                "variable": 1, "output": 1}
# Consume comments, quoted strings and heredocs as whole tokens. A declaration
# inside one of these must never be mistaken for an actual top-level block.
TOKENS = re.compile(
    r'(?P<comment>\#[^\n]*|//[^\n]*|/\*[\s\S]*?\*/)'
    r'|(?P<heredoc><<-?\s*(?P<delimiter>[A-Za-z_][\w]*)[^\n]*\n'
    r'[\s\S]*?^\s*(?P=delimiter)\s*$)'
    r'|(?P<string>"(?:\\.|[^"\\])*")'
    r'|(?P<word>[A-Za-z_][\w-]*)|(?P<brace>[{}])|(?P<other>\S)',
    re.MULTILINE,
)


def _declaration(filename, kind, labels, line):
    if kind in {"resource", "data"}:
        address = ".".join(labels)
        if kind == "data":
            address = "data." + address
        resource_type = labels[0]
    else:
        address = kind + "." + labels[0]
        resource_type = None
    return {
        "kind": kind, "address": address, "name": labels[-1],
        "resource_type": resource_type,
        "module_path": str(PurePosixPath(filename).parent),
        "source_file": filename, "line": line,
        "status": "declared_in_source", "runtime_status": "unverified",
    }


def discover_terraform(entries):
    """Inventory HCL and Terraform JSON block labels, never attribute values."""
    declarations, files, warnings = [], [], []
    for filename, source in sorted(entries):
        if not filename.lower().endswith((".tf", ".tf.json")):
            continue
        files.append(filename)
        if filename.lower().endswith(".tf.json"):
            try:
                document = json.loads(source)
                if not isinstance(document, dict):
                    raise ValueError("Root must be an object")
                for kind, count in BLOCK_LABELS.items():
                    blocks = document.get(kind, {})
                    if not isinstance(blocks, dict):
                        continue
                    for label, body in blocks.items():
                        if count == 2 and isinstance(body, dict):
                            for name in body:
                                declarations.append(_declaration(filename, kind, [label, name], None))
                        elif count == 1:
                            declarations.append(_declaration(filename, kind, [label], None))
            except (ValueError, TypeError):
                warnings.append(f"Invalid Terraform JSON: {filename}")
            continue
        tokens = [token for token in TOKENS.finditer(source)
                  if token.lastgroup != "comment"]
        depth = 0
        for index, token in enumerate(tokens):
            value = token.group()
            if depth == 0 and token.lastgroup == "word" and value in BLOCK_LABELS:
                count = BLOCK_LABELS[value]
                following = tokens[index + 1:index + count + 2]
                labels = following[:count]
                if (len(following) == count + 1 and following[-1].group() == "{"
                        and all(label.lastgroup in {"string", "word"} for label in labels)):
                    try:
                        names = [json.loads(label.group()) if label.lastgroup == "string"
                                 else label.group() for label in labels]
                    except ValueError:
                        warnings.append(f"Unsupported HCL label escape: {filename}")
                        continue
                    declarations.append(_declaration(
                        filename, value, names, source.count("\n", 0, token.start()) + 1,
                    ))
            if token.lastgroup == "brace":
                depth += 1 if value == "{" else -1
                if depth < 0:
                    break
        if depth != 0:
            warnings.append(f"Unbalanced HCL braces; inventory may be partial: {filename}")
    return {
        "files": files, "declarations": declarations,
        "declaration_count": len(declarations),
        "resource_count": sum(item["kind"] == "resource" for item in declarations),
        "warnings": warnings + [
            "Static declarations only; no Terraform init, plan, apply or state access.",
            "Attributes, module expansion, provider aliases, count and for_each instances are not resolved.",
        ],
    }
