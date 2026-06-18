import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from athena.config import settings

router = APIRouter(prefix="/api/files")

# 500 MB cap so a runaway upload can't exhaust disk
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


@router.post("/upload")
async def upload_file(file: UploadFile) -> dict[str, str]:
    """Save an uploaded file to ~/.athena/uploads/ and return its absolute path
    so it can be used by file-loader nodes (csv_loader, excel_loader, etc.)."""
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Strip any directory components so the client can't write outside upload_dir
    raw_name = file.filename or "upload"
    safe_name = Path(raw_name).name or "upload"
    dest = upload_dir / safe_name

    # Don't clobber an existing file — append a unix timestamp suffix
    if dest.exists():
        dest = upload_dir / f"{Path(safe_name).stem}_{int(time.time())}{Path(safe_name).suffix}"

    total = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    413,
                    detail={"detail": f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit", "code": "FILE_TOO_LARGE"},
                )
            out.write(chunk)

    return {"path": str(dest), "name": dest.name, "size": str(total)}
