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
            extraction_result = await process_upload_file(uploaded_file)

            # Save _text.txt and _bboxes.json
            from utils.file_saver import get_output_path, save_text, save_json

            base_filename = file_name
            if "." in base_filename:
                base_filename = base_filename.rsplit(".", 1)[0]

            # 1. Save _text.txt
            text_path = get_output_path(base_filename, suffix="_text", extension=".txt", prefix="02")
            save_text(text_path, extraction_result["result_text"])

            # 2. Save _bboxes.json
            bboxes_path = get_output_path(base_filename, suffix="_bboxes", extension=".json", prefix="03")

            # Construct strict JSON structure
            line_metadata = extraction_result["bounding_boxes"].get("line_metadata", [])
            # ensure each line has required keys
            lines_list = []
            max_page = 0
            for line in line_metadata:
                li = {
                    "line_index": line.get("line_index"),
                    "page": int(line.get("page", 1)),
                    "bbox": line.get("bbox") or line.get("raw_box") or [0, 0, 0, 0],
                    "text": line.get("text", ""),
                }
                lines_list.append(li)
                if li["page"] and li["page"] > max_page:
                    max_page = li["page"]

            bboxes_data = {
                "text": extraction_result["result_text"],
                "pages": max_page or 1,
                "lines": lines_list,
            }
            logger.info(f"Saving bboxes to {bboxes_path}. Data keys: {list(bboxes_data.keys())}. Lines count: {len(bboxes_data['lines'])}")
            save_json(bboxes_path, bboxes_data)

            logger.info(f"Saved outputs: {text_path}, {bboxes_path}")

            # Format response using utility function
            formatted = format_upload_response(extraction_result)
            responses.append(UploadResponse(**formatted))

            logger.info(f"Successfully processed file: {file_name}")

        except HTTPException as exc:
            error_msg = f"Failed to process '{file_name}': {exc.detail}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=exc.status_code,
                detail=error_msg,
            ) from exc
        except ValueError as exc:
            error_msg = f"Invalid data for '{file_name}': {str(exc)}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg,
            ) from exc
        except Exception as exc:
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
