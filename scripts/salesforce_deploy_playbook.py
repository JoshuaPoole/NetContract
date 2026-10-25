"""Approved Salesforce object + permission deployment and field visibility verification.

Runs locally using the Salesforce CLI already authenticated on this machine.
No secrets are read, logged or stored by this script.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

NS = {"sf": "http://soap.sforce.com/2006/04/metadata"}
SFNS = NS["sf"]


def run_sf(executable, *args, cwd=None):
    command = [executable, *args, "--json"]
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=900, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Salesforce CLI did not return JSON (exit {result.returncode}): {result.stderr[:500]}") from exc
    if result.returncode or payload.get("status") != 0:
        details = payload.get("message") or (payload.get("result") or {}).get("errorMessage") or result.stderr
        raise RuntimeError(f"Salesforce command failed: {str(details)[:800]}")
    return payload.get("result") or {}


def inspect_objects(source):
    if not source.is_dir():
        raise ValueError(f"Object source directory does not exist: {source}")
    objects = {}
    for folder in sorted(source.iterdir()):
        if not folder.is_dir():
            continue
        object_name = folder.name
        if not object_name.endswith("__c") or not (folder / f"{object_name}.object-meta.xml").is_file():
            continue
        fields = []
        for file in sorted((folder / "fields").glob("*.field-meta.xml")):
            ET.parse(file)  # fail before any org changes if metadata is malformed
            fields.append(file.name.removesuffix(".field-meta.xml"))
        ET.parse(folder / f"{object_name}.object-meta.xml")
        if fields:
            objects[object_name] = fields
    if not objects:
        raise ValueError("No custom objects with custom field metadata found")
    return objects


def generate_permissions(objects, destination):
    # Stable application-specific name: repeated runs update the same permission set.
    fingerprint = hashlib.sha256("|".join(sorted(objects)).encode()).hexdigest()[:12]
    name = f"ContractCyber_{fingerprint}_Access"
    root = ET.Element(f"{{{SFNS}}}PermissionSet")
    ET.SubElement(root, f"{{{SFNS}}}label").text = f"ContractCyber {fingerprint} Access"
    # Salesforce requires all objectPermissions BEFORE fieldPermissions.
    for object_name in sorted(objects):
        block = ET.SubElement(root, f"{{{SFNS}}}objectPermissions")
        for key, value in (
            ("allowCreate", "true"), ("allowDelete", "false"), ("allowEdit", "true"),
            ("allowRead", "true"), ("modifyAllRecords", "false"),
            ("object", object_name), ("viewAllRecords", "false"),
        ):
            ET.SubElement(block, f"{{{SFNS}}}{key}").text = value
    for object_name in sorted(objects):
        for field in objects[object_name]:
            block = ET.SubElement(root, f"{{{SFNS}}}fieldPermissions")
            for key, value in (("editable", "true"), ("field", f"{object_name}.{field}"), ("readable", "true")):
                ET.SubElement(block, f"{{{SFNS}}}{key}").text = value
    destination.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("", SFNS)
    ET.ElementTree(root).write(destination / f"{name}.permissionset-meta.xml", encoding="utf-8", xml_declaration=True)
    return name



def normalize_frontend_url(value):
    """Accept an explicit HTTPS UI URL; credentials never belong in metadata."""
    if not value:
        return ""
    value = value.strip()
    if len(value) > 2048 or any(ord(char) <= 32 for char in value) or "\\" in value:
        raise ValueError("Use a valid HTTPS frontend URL without whitespace")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise ValueError("Invalid frontend URL") from exc
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("Frontend URL must use HTTPS with no embedded credentials, query or fragment")
    return urlunsplit((url.scheme, url.netloc.lower(), url.path or "/", "", ""))


def generate_frontend_workspace(default, permission_name, frontend_url, objects=None):
    """Wrap the existing hosted frontend; its request logic stays on its origin."""
    frontend_url = normalize_frontend_url(frontend_url)
    suffix = hashlib.sha256(permission_name.encode()).hexdigest()[:12]
    component = "lifeAfterCode" + suffix
    tab_name = permission_name.removesuffix("_Access") + "_Workspace"
    folder = default / "lwc" / component
    folder.mkdir(parents=True, exist_ok=True)
    templates = Path(__file__).with_name("salesforce_workspace")
    bridge = urlsplit(frontend_url).path.rstrip('/') == '/mim' and bool(objects)
    reader_class = "LifeAfterCodeReader" + suffix
    if bridge:
        import re
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', value)
               for name, fields in objects.items() for value in [name, *fields]):
            raise ValueError('Invalid record reader scope identifier')
        classes = default / 'classes'
        classes.mkdir(exist_ok=True)
        scope = ', '.join("'" + name + "' => '" + ', '.join(sorted(fields)) + "'"
                          for name, fields in sorted(objects.items()))
        for template_name, class_name in [('reader.cls', reader_class), ('readerTest.cls', reader_class + 'Test')]:
            code = (templates / template_name).read_text(encoding='utf-8').replace('__CLASS__', reader_class)
            code = code.replace('__SCOPE__', scope).replace('__FIRST_OBJECT__', sorted(objects)[0])
            (classes / (class_name + '.cls')).write_text(code, encoding='utf-8')
            (classes / (class_name + '.cls-meta.xml')).write_text(
                '<?xml version="1.0" encoding="UTF-8"?><ApexClass xmlns="' + SFNS + '"><apiVersion>65.0</apiVersion><status>Active</status></ApexClass>', encoding='utf-8')
    for extension in ("html", "js", "css", "js-meta.xml"):
        content = (templates / ("workspace." + extension)).read_text(encoding="utf-8")
        if extension == "js":
            content = content.replace("__FRONTEND_URL__", json.dumps(frontend_url))
            content = content.replace('__RECORD_IMPORT__', "import readRecords from '@salesforce/apex/" + reader_class + ".readRecords';" if bridge else '')
            content = content.replace('__RECORD_READER__', 'readRecords' if bridge else 'null')
            content = content.replace('__BRIDGE_ENABLED__', 'true' if bridge else 'false')
            content = content.replace('__OBJECT_OPTIONS__', json.dumps([{'label': name, 'value': name} for name in sorted(objects or {})]))
        (folder / (component + "." + extension)).write_text(content, encoding="utf-8")
    tab = ET.Element(f"{{{SFNS}}}CustomTab")
    for name, value in (("label", "MIM Workspace"), ("lwcComponent", component), ("motif", "Custom19: Wrench")):
        ET.SubElement(tab, f"{{{SFNS}}}{name}").text = value
    (default / "tabs").mkdir(exist_ok=True)
    ET.ElementTree(tab).write(default / "tabs" / f"{tab_name}.tab-meta.xml", encoding="utf-8", xml_declaration=True)
    url = urlsplit(frontend_url)
    origin = urlunsplit((url.scheme, url.netloc, "", "", ""))
    trusted_name = "LifeAfterCodeRuntime_" + hashlib.sha256(origin.encode()).hexdigest()[:12]
    trusted = ET.Element(f"{{{SFNS}}}CspTrustedSite")
    values = (("context", "All"), ("description", "Hosted MIM workspace frame"),
              ("endpointUrl", origin), ("isActive", "true"),
              ("isApplicableToConnectSrc", "false"), ("isApplicableToFontSrc", "false"),
              ("isApplicableToFrameSrc", "true"), ("isApplicableToImgSrc", "false"),
              ("isApplicableToMediaSrc", "false"), ("isApplicableToStyleSrc", "false"))
    for name, value in values:
        ET.SubElement(trusted, f"{{{SFNS}}}{name}").text = value
    (default / "cspTrustedSites").mkdir(exist_ok=True)
    ET.ElementTree(trusted).write(default / "cspTrustedSites" / f"{trusted_name}.cspTrustedSite-meta.xml", encoding="utf-8", xml_declaration=True)
    return {"url": frontend_url, "origin": origin, "tab": tab_name,
            "component": component, "trusted_site": trusted_name, "reader_class": reader_class if bridge else None}


def generate_lightning_app(objects, default, permission_name, label, frontend_url=""):
    """Add standard record tabs and app visibility to the scoped permission set."""
    if not label.strip() or len(label) > 40:
        raise ValueError("App label must contain 1 to 40 characters")
    app_name = permission_name.removesuffix("_Access") + "_App"
    for object_name in sorted(objects):
        root = ET.Element(f"{{{SFNS}}}CustomTab")
        ET.SubElement(root, f"{{{SFNS}}}customObject").text = "true"
        ET.SubElement(root, f"{{{SFNS}}}motif").text = "Custom19: Wrench"
        folder = default / "tabs"
        folder.mkdir(exist_ok=True)
        ET.ElementTree(root).write(folder / f"{object_name}.tab-meta.xml", encoding="utf-8", xml_declaration=True)
    root = ET.Element(f"{{{SFNS}}}CustomApplication")
    ET.SubElement(root, f"{{{SFNS}}}formFactors").text = "Large"
    ET.SubElement(root, f"{{{SFNS}}}label").text = label
    ET.SubElement(root, f"{{{SFNS}}}navType").text = "Standard"
    workspace = generate_frontend_workspace(default, permission_name, frontend_url, objects) if frontend_url else None
    if workspace:
        ET.SubElement(root, f"{{{SFNS}}}tabs").text = workspace["tab"]
    for object_name in sorted(objects):
        ET.SubElement(root, f"{{{SFNS}}}tabs").text = object_name
    ET.SubElement(root, f"{{{SFNS}}}uiType").text = "Lightning"
    folder = default / "applications"
    folder.mkdir(exist_ok=True)
    ET.ElementTree(root).write(folder / f"{app_name}.app-meta.xml", encoding="utf-8", xml_declaration=True)
    path = default / "permissionsets" / f"{permission_name}.permissionset-meta.xml"
    tree = ET.parse(path)
    root = tree.getroot()
    visibility = ET.Element(f"{{{SFNS}}}applicationVisibilities")
    ET.SubElement(visibility, f"{{{SFNS}}}application").text = app_name
    ET.SubElement(visibility, f"{{{SFNS}}}visible").text = "true"
    root.insert(0, visibility)
    if workspace and workspace.get('reader_class'):
        access = ET.Element(f"{{{SFNS}}}classAccesses")
        ET.SubElement(access, f"{{{SFNS}}}apexClass").text = workspace['reader_class']
        ET.SubElement(access, f"{{{SFNS}}}enabled").text = 'true'
        root.insert(1, access)
    tab_names = sorted(objects) + ([workspace["tab"]] if workspace else [])
    for object_name in tab_names:
        tab = ET.SubElement(root, f"{{{SFNS}}}tabSettings")
        ET.SubElement(tab, f"{{{SFNS}}}tab").text = object_name
        ET.SubElement(tab, f"{{{SFNS}}}visibility").text = "Visible"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return app_name


def verify_fields(executable, org, objects):
    failures = []
    for object_name, fields in objects.items():
        result = run_sf(executable, "sobject", "describe", "--sobject", object_name, "--target-org", org)
        visible = {item["name"]: item for item in result.get("fields", [])}
        for field in fields:
            found = visible.get(field)
            if not found or not found.get("createable"):
                failures.append(f"{object_name}.{field}: missing or not createable")
        print(f"{object_name}: {len(fields)} expected custom fields checked")
    if failures:
        raise RuntimeError("Post-deployment field verification failed: " + "; ".join(failures))
    print("PASS: all approved custom fields visible and createable")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects-dir", required=True, type=Path, help="Directory containing ONLY approved application object metadata")
    parser.add_argument("--org", default="hackfest-developer")
    parser.add_argument("--approve", action="store_true", help="Explicitly authorize metadata and permission deployment")
    parser.add_argument("--assign-to-current-user", action="store_true", help="Explicitly authorize assigning generated permission set to logged-in user")
    parser.add_argument("--verify-only", action="store_true", help="Read-only describe verification; no deployment")
    parser.add_argument("--validate-only", action="store_true", help="Check-only deployment; no assignment or field verification")
    parser.add_argument("--frontend-url", default="", help="Existing hosted HTTPS frontend, such as its /alexa URL")
    parser.add_argument("--app-label", help="Also generate a Lightning app and tabs (1 to 40 characters)")
    args = parser.parse_args(argv)
    if args.validate_only and (args.approve or args.assign_to_current_user or args.verify_only):
        parser.error("--validate-only cannot be combined with deployment, assignment or verify-only")
    if args.verify_only and (args.approve or args.assign_to_current_user or args.app_label):
        parser.error("--verify-only cannot be combined with deployment, assignment or app generation")
    if args.app_label is not None and (not args.app_label.strip() or len(args.app_label) > 40):
        parser.error("App label must contain 1 to 40 characters")
    args.frontend_url = normalize_frontend_url(args.frontend_url)
    if args.frontend_url and (not args.app_label or args.verify_only):
        parser.error("--frontend-url requires --app-label and deployment or validation mode")
    executable = shutil.which("sf.cmd") or shutil.which("sf")
    if not executable:
        parser.error("Salesforce CLI not found on PATH (sf.cmd on Windows)")
    objects = inspect_objects(args.objects_dir)
    print(f"Scope: {len(objects)} objects, {sum(map(len, objects.values()))} custom fields; org alias: {args.org}")
    if args.verify_only:
        verify_fields(executable, args.org, objects)
        return
    if not args.approve and not args.validate_only:
        parser.error("Deployment requires --approve; use --verify-only for read-only checks")
    if args.assign_to_current_user and not args.approve:
        parser.error("Permission assignment requires --approve")
    # Windows CLI helper processes can retain their cwd after sf.cmd returns.
    # Best-effort cleanup must not overwrite the actual Salesforce result.
    with tempfile.TemporaryDirectory(prefix="contractcyber-sf-", ignore_cleanup_errors=True) as temp:
        project = Path(temp)
        default = project / "force-app" / "main" / "default"
        dest_objects = default / "objects"
        dest_objects.mkdir(parents=True)
        for object_name in objects:
            shutil.copytree(args.objects_dir / object_name, dest_objects / object_name)
        permission_name = generate_permissions(objects, default / "permissionsets")
        if args.app_label:
            app_name = generate_lightning_app(objects, default, permission_name, args.app_label, args.frontend_url)
            print(f"Lightning app: {app_name} ({args.app_label}); {len(objects)} object tabs")
        (project / "sfdx-project.json").write_text(json.dumps({
            "packageDirectories": [{"path": "force-app", "default": True}],
            "namespace": "", "sourceApiVersion": "65.0",
        }), encoding="utf-8")
        flags = ["--dry-run"] if args.validate_only else []
        result = run_sf(executable, "project", "deploy", "start", "--source-dir",
                        str(default), "--target-org", args.org, "--wait", "15", *flags, cwd=project)
        if result.get("status") != "Succeeded":
            raise RuntimeError(f"Deployment not confirmed successful: {result.get('status')}; deployment ID: {result.get('id')}")
        if args.validate_only:
            print(f"Check-only validation succeeded: {result.get('id')}; no metadata deployed or permissions assigned")
            return
        print(f"Deployment succeeded: {result.get('id')} (permission set: {permission_name})")
        if args.assign_to_current_user:
            run_sf(executable, "org", "assign", "permset", "--name", permission_name, "--target-org", args.org)
            print("Generated permission set assigned to authenticated org user")
    verify_fields(executable, args.org, objects)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


