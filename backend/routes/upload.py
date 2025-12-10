from typing import List, Optional, Union

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from services.llmwhisperer_service import process_upload_file
from utils.file_utils import validate_file_extension
from utils.response_formatters import format_upload_response


class UploadResponse(BaseModel):
    fileName: str
    text: str
    whisperHash: str
    # LLMWhisperer returns line_metadata as a list; allow dict or list to avoid validation failure.
    boundingBoxes: Optional[Union[dict, list]] = None
    pages: Optional[List[dict]] = None


router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("", response_model=List[UploadResponse])
async def upload_files(files: List[UploadFile] = File(...)) -> List[UploadResponse]:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided.",
        )

    responses: List[UploadResponse] = []

    for uploaded_file in files:
        validate_file_extension(uploaded_file)

        try:
            extraction_result = await process_upload_file(uploaded_file)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to process '{uploaded_file.filename}': {exc}",
            ) from exc

        formatted = format_upload_response(extraction_result)
        responses.append(UploadResponse(**formatted))

    return responses
