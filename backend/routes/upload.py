import logging
from typing import List, Optional, Union

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from services.llmwhisperer_service import process_upload_file
from utils.file_utils import validate_file_extension
from utils.response_formatters import format_upload_response

logger = logging.getLogger(__name__)


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
    """
    Upload multiple files for document extraction.
    
    Accepts form-data with multiple files and processes them through LLMWhisperer.
    Each file is processed with:
    - output_mode: "layout_preserving"
    - add_line_nos: True
    - wait_for_completion: True (via polling)
    
    Returns an array of extraction results with:
    - fileName: Original filename
    - text: Extracted text content
    - whisperHash: Unique identifier for the extraction
    - boundingBoxes: Word-level bounding box metadata
    - pages: Page metadata
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided.",
        )

    responses: List[UploadResponse] = []

    for uploaded_file in files:
        file_name = uploaded_file.filename or "unknown"
        
        try:
            # Validate file extension
            validate_file_extension(uploaded_file)
            
            logger.info(f"Processing file: {file_name}")
            
            # Process file through LLMWhisperer service
            # This handles:
            # - Reading file bytes
            # - Calling LLMWhisperer with layout_preserving mode and line numbers
            # - Polling until completion
            # - Extracting result_text, whisper_hash, pages, and bounding_boxes
            extraction_result = await process_upload_file(uploaded_file)
            
            # Format response using utility function
            formatted = format_upload_response(extraction_result)
            responses.append(UploadResponse(**formatted))
            
            logger.info(f"Successfully processed file: {file_name}")
            
        except HTTPException as exc:
            # Re-raise HTTP exceptions (they already have proper status codes)
            error_msg = f"Failed to process '{file_name}': {exc.detail}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=exc.status_code,
                detail=error_msg,
            ) from exc
        except ValueError as exc:
            # Validation errors
            error_msg = f"Invalid data for '{file_name}': {str(exc)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg,
            ) from exc
        except Exception as exc:
            # Unexpected errors
            error_msg = f"Unexpected error processing '{file_name}': {str(exc)}"
            logger.exception(error_msg)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_msg,
            ) from exc

    if not responses:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No files were successfully processed.",
        )

    logger.info(f"Successfully processed {len(responses)} file(s)")
    return responses
