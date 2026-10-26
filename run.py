"""Start LifeAfterCode or release its reviewed metadata through the existing playbook."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
MAX_ARCHIVE_BYTES = 20_000_000
MAX_UNCOMPRESSED_BYTES = 30_000_000


def prepare_reviewed_bundle(archive_path, destination):
    """Reproduce approved metadata and reject extra or mismatched ZIP contents.

    The app checks source evidence before exporting this ZIP. This local runner
    checks its review decisions and matching metadata; it does not re-scan source.
    Repository ZIPs and Terraform evidence exports are not deployment inputs.
    """
    from app.reviewed_metadata import ReviewedCanonicalPlan, export_reviewed_metadata

    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Reviewed metadata ZIP exceeds 20 MB")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(entries) > 1000 or len(names) != len(set(names))
                or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES):
            raise ValueError("Metadata ZIP has duplicate entries or exceeds its scan budget")
        if "canonical-review.json" not in names:
            raise ValueError("Use the reviewed Salesforce metadata ZIP downloaded from /salesforce")
        plan = ReviewedCanonicalPlan.model_validate_json(archive.read("canonical-review.json"))
        field_count = export_reviewed_metadata(plan, destination)
        expected = {path.relative_to(destination).as_posix(): path
                    for path in destination.rglob("*") if path.is_file()}
        if set(names) != set(expected) | {"canonical-review.json"}:
            raise ValueError("Metadata ZIP contains files outside the approved review")
        for name, generated in expected.items():
            actual = archive.read(name).decode("utf-8").replace("\r\n", "\n")
            if actual != generated.read_text(encoding="utf-8"):
                raise ValueError(f"Metadata differs from the approved review: {name}")
    return field_count


def release_review(args):
    """Validate first, then optionally reuse the existing approved-deploy path."""
    from scripts.salesforce_deploy_playbook import main as run_playbook

    if args.assign_to_current_user and not args.approve:
        raise ValueError("Permission assignment requires --approve")
    with tempfile.TemporaryDirectory(prefix="lifeaftercode-review-", ignore_cleanup_errors=True) as directory:
        destination = Path(directory) / "reviewed"
        count = prepare_reviewed_bundle(args.metadata_zip, destination)
        objects = destination / "force-app" / "main" / "default" / "objects"
        print(f"Reviewed bundle: {count} approved fields; target org alias: {args.org}")
        if not (shutil.which("sf.cmd") or shutil.which("sf")):
            raise RuntimeError(
                "Salesforce CLI is unavailable here. Run this command on your authenticated "
                "Salesforce workstation (sf.cmd on Windows)."
            )
        scope = ["--objects-dir", str(objects), "--org", args.org,
                 "--app-label", args.app_label]
        if args.frontend_url:
            scope += ["--frontend-url", args.frontend_url]
        run_playbook([*scope, "--validate-only"])
        if not args.approve:
            print("Validation complete; nothing deployed. Add --approve to deploy this reviewed bundle.")
            return
        flags = ["--approve"]
        if args.assign_to_current_user:
            flags.append("--assign-to-current-user")
        run_playbook([*scope, *flags])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="Start the discovery UI at /")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--workspace", type=Path, default=ROOT / "workspace")
    serve.add_argument("--reload", action="store_true")
    salesforce = commands.add_parser("salesforce", help="Validate or deploy a reviewed Salesforce ZIP")
    salesforce.add_argument("--metadata-zip", required=True, type=Path)
    salesforce.add_argument("--org", default="hackfest-developer")
    salesforce.add_argument("--frontend-url", default="", help="Embed the existing hosted HTTPS frontend in a MIM Workspace tab")
    salesforce.add_argument("--app-label", default="LifeAfterCode")
    salesforce.add_argument("--approve", action="store_true", help="Deploy after successful validation")
    salesforce.add_argument("--assign-to-current-user", action="store_true",
                            help="Assign the scoped permission set after deployment")
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve"])
    if args.command == "salesforce":
        release_review(args)
        return
    import uvicorn

    os.environ["MAPPER_WORKSPACE"] = str(args.workspace.resolve())
    os.environ["LIFEAFTERCODE_BROWSER_DEPLOY"] = (
        "1" if args.host in {"127.0.0.1", "localhost", "::1"} else "0"
    )
    print(f"Discovery: http://{args.host}:{args.port}/")
    print("Salesforce review: follow the mappings link after scanning a repository.")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1,::1")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
