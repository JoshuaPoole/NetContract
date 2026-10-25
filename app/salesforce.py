"""Generate REVIEW-ONLY Salesforce custom object metadata. No automatic deployment."""

from pathlib import Path
from xml.sax.saxutils import escape
from .models import Analysis
import re
import hashlib


def api_name(value: str):
    name = re.sub(r"[^A-Za-z0-9_]", "_", value)
    name = re.sub(r"_+", "_", name).strip("_")

    if not name or not name[0].isalpha():
        name = "M_" + name

    name = name[:35].rstrip("_")

    if not name:
        raise ValueError("Invalid Salesforce API name")

    return name


def repository_namespace(repository_id: str) -> str:
    """Generate a short, Salesforce-safe repository namespace."""
    digest = hashlib.sha256(repository_id.encode("utf-8")).hexdigest()[:8]

    return f"R{digest}"


def object_api_name(repository_id: str, module_name: str) -> str:
    """Generate a repository-isolated Salesforce object name."""
    namespace = repository_namespace(repository_id)

    # Keep the final API name within Salesforce's 40-character limit.
    available = 40 - len(namespace) - len("__c") - 1

    module = api_name(module_name)[:available].rstrip("_")

    return f"{namespace}_{module}__c"


def generate_metadata(
    analysis: Analysis,
    destination: Path,
    repository_id: str,
):
    """Generate Salesforce metadata isolated by repository."""

    count = 0
    seen_objects = set()

    for module in analysis.modules:
        approved = [field for field in module.fields if field.status == "approved"]

        if not approved:
            continue

        object_name = object_api_name(repository_id, module.name)

        if object_name.lower() in seen_objects:
            raise ValueError(f"Duplicate generated object: {object_name}")

        seen_objects.add(object_name.lower())

        root = destination / "force-app" / "main" / "default" / "objects" / object_name

        (root / "fields").mkdir(parents=True, exist_ok=True)

        label = "Procedure" if module.name == "DIP" else module.name[:40]

        (root / f"{object_name}.object-meta.xml").write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
<label>{escape(label)}</label>
<pluralLabel>{escape(label)} Records</pluralLabel>
<deploymentStatus>Deployed</deploymentStatus>
<sharingModel>ReadWrite</sharingModel>
<nameField>
<label>Name</label>
<type>Text</type>
</nameField>
</CustomObject>""",
            encoding="utf-8",
        )

        seen_fields = set()

        for field in approved:
            field_name = api_name(field.target.removesuffix("__c")) + "__c"

            if field_name.lower() in seen_fields:
                raise ValueError(f"Duplicate generated field: {field_name}")

            seen_fields.add(field_name.lower())

            typ = field.data_type

            if typ not in {"Text", "LongTextArea", "Number", "Checkbox", "Date", "DateTime", "Email"}:
                raise ValueError(f"Unsupported Salesforce field type: {typ}")

            details = {
                "Text": "<length>255</length>",
                "LongTextArea": "<length>131072</length><visibleLines>4</visibleLines>",
                "Number": ("<precision>18</precision><scale>2</scale>"),
                "Checkbox": "<defaultValue>false</defaultValue>",
            }.get(typ, "")

            field_label = field_name.removesuffix("__c").replace("_", " ")

            (root / "fields" / f"{field_name}.field-meta.xml").write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<CustomField xmlns="http://soap.sforce.com/2006/04/metadata">
<fullName>{escape(field_name)}</fullName>
<label>{escape(field_label)}</label>
<type>{typ}</type>
{details}
</CustomField>""",
                encoding="utf-8",
            )

            count += 1

    return count


