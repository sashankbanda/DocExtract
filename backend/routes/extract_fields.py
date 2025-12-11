import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.mapping_service import extract_fields_from_text, normalize_bounding_boxes
from utils.file_saver import get_output_path, save_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract-fields", tags=["extract-fields"])


class ExtractFieldsRequest(BaseModel):
    """Request model for field extraction."""

    text: str = Field(..., description="Layout-preserving text from LLMWhisperer")
    boundingBoxes: Optional[Union[Dict[str, Any], List[Any]]] = Field(
        default=None,
        description="Bounding box metadata from LLMWhisperer (dict or list)",
    )
    fileName: Optional[str] = Field(default=None, description="Original filename for output naming")


class Citation(BaseModel):
    """Model for a single citation."""
    page: int
    bbox: List[int]
    line_index: int


class FieldData(BaseModel):
    """Model for individual field data."""

    value: str
    citations: List[Citation] = Field(default_factory=list)


class ExtractFieldsResponse(BaseModel):
    """Response model for field extraction."""

    text: str
    fields: Dict[str, FieldData]
    bounding_boxes: Dict[str, Any]


@router.post("", response_model=ExtractFieldsResponse)
async def extract_fields(request: ExtractFieldsRequest) -> ExtractFieldsResponse:
    """
    Extract structured fields from layout-preserving text using template.

    This endpoint:
    1. Loads the specified template JSON
    2. Uses Groq LLM to extract field values from the text
    3. Maps field values to citations (page, bbox, line_index) using robust matching
    4. Returns structured field data with full citations
    """
    # Validate input
    if not request.text or not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text cannot be empty.",
        )

    try:
        # Normalize bounding boxes (convert list to dict, handle None)
        normalized_boxes = normalize_bounding_boxes(request.boundingBoxes)
        logger.info(f"Normalized bounding boxes: type={type(normalized_boxes).__name__}, keys={len(normalized_boxes) if isinstance(normalized_boxes, dict) else 'N/A'}")

        # Extract fields using mapping service
        logger.info(f"Extracting fields from text (length: {len(request.text)})")
        result = await extract_fields_from_text(
            text=request.text,
            bounding_boxes=normalized_boxes,
        )

        # Convert to response format
        fields_dict: Dict[str, FieldData] = {}
        for field_key, field_data in result.get("fields", {}).items():
            raw_citations = field_data.get("citations", [])
            citations = [
                Citation(
                    page=c.get("page", 1),
                    bbox=c.get("bbox", [0, 0, 0, 0]),
                    line_index=c.get("line_index", 0)
                ) for c in raw_citations
            ]
            
            fields_dict[field_key] = FieldData(
                value=field_data.get("value", ""),
                citations=citations,
            )

        logger.info(f"Successfully extracted {len(fields_dict)} fields")
        
        # Save structured fields to output_files/ as 04_<filename>_structured.json
        try:
            import hashlib
            # Try to extract whisperHash from boundingBoxes if available
            # Determine filename for output
            filename = None
            if request.fileName:
                filename = request.fileName
                # Remove extension if present
                if "." in filename:
                    filename = filename.rsplit(".", 1)[0]
            
            if not filename and isinstance(normalized_boxes, dict):
                whisper_hash = normalized_boxes.get("whisperHash") or normalized_boxes.get("whisper_hash")
                if whisper_hash:
                    filename = f"file_{str(whisper_hash)[:12]}"
            
            # Fallback to text hash if no filename found
            if not filename:
                text_hash = hashlib.md5(request.text.encode()).hexdigest()[:12]
                filename = f"extracted_{text_hash}"
            
            structured_path = get_output_path(filename, suffix="_structured", extension=".json", prefix="04")
            
            # Construct strict JSON structure for _structured.json
            structured_data = {
                "file_id": filename,
                "extracted_fields": {}
            }
            
            for field_key, field_obj in fields_dict.items():
                structured_data["extracted_fields"][field_key] = {
                    "value": field_obj.value,
                    "citations": [
                        {
                            "page": c.page,
                            "line_index": c.line_index,
                            "bbox": c.bbox
                        }
                        for c in field_obj.citations
                    ]
                }

            save_json(structured_path, structured_data)
            logger.info("Saved structured fields to %s", structured_path)
        except Exception as e:
            logger.warning(f"Failed to save structured fields: {e}")
            # Continue processing even if saving fails
        
        return ExtractFieldsResponse(
            text=request.text,
            fields=fields_dict,
            bounding_boxes=normalized_boxes or {},
        )
    except ValueError as exc:
        error_msg = f"Invalid template or data: {str(exc)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        ) from exc
    except Exception as exc:
        error_msg = f"Field extraction failed: {str(exc)}"
        logger.exception(error_msg)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error_msg,
        ) from exc
