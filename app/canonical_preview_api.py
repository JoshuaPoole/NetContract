"""Read-only reviewed canonical Salesforce metadata preview API."""
import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .reviewed_metadata import ReviewedCanonicalPlan, export_reviewed_metadata

router = APIRouter()


@router.post("/api/canonical/metadata.zip")
def canonical_metadata_preview(plan: ReviewedCanonicalPlan):
    """Download reviewed metadata; does not call Salesforce or change project state."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_reviewed_metadata(plan, root)
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in root.rglob("*"):
                    if file.is_file():
                        archive.write(file, file.relative_to(root))
            data.seek(0)
            return StreamingResponse(
                data,
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="canonical-metadata.zip"'},
            )
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

