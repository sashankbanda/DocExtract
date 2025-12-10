import os
from typing import Set

from fastapi import HTTPException, UploadFile, status


ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".docx", ".xlsx"}


def validate_file_extension(upload_file: UploadFile) -> None:
    _, extension = os.path.splitext(upload_file.filename or "")
    if extension.lower() not in ALLOWED_EXTENSIONS:
        allowed_display = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{extension}'. Allowed types: {allowed_display}",
        )
