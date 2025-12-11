import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.mapping_service import _load_template, extract_fields_from_text, normalize_bounding_boxes
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
    templateName: str = Field(
        default="standard_template",
        description="Name of the template to use (without .json extension)",
    )


class FieldData(BaseModel):
    """Model for individual field data."""

    value: str
    start: Optional[int] = None
    end: Optional[int] = None
    word_indexes: list[int] = Field(default_factory=list)


class ExtractFieldsResponse(BaseModel):
    """Response model for field extraction."""

    fields: Dict[str, FieldData]


@router.post("", response_model=ExtractFieldsResponse)
async def extract_fields(request: ExtractFieldsRequest) -> ExtractFieldsResponse:
    """
    Extract structured fields from layout-preserving text using template.

    This endpoint:
    1. Loads the specified template JSON
    2. Uses Groq LLM to extract field values from the text
    3. Maps word indexes (start/end) to word_indexes arrays
    4. Returns structured field data

    Args:
        request: ExtractFieldsRequest with text, boundingBoxes, and optional templateName

    Returns:
        ExtractFieldsResponse with extracted fields

    Raises:
        HTTPException: If text is empty, template not found, or extraction fails
    """
    # Validate input
    if not request.text or not request.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text cannot be empty.",
        )

    template_name = request.templateName or "standard_template"

    try:
        # Load template
        logger.info(f"Loading template: {template_name}")
        template = _load_template(template_name)

        # Normalize bounding boxes (convert list to dict, handle None)
        normalized_boxes = normalize_bounding_boxes(request.boundingBoxes)
        logger.info(f"Normalized bounding boxes: type={type(normalized_boxes).__name__}, keys={len(normalized_boxes) if isinstance(normalized_boxes, dict) else 'N/A'}")

        # Extract fields using mapping service
        logger.info(f"Extracting fields from text (length: {len(request.text)})")
        result = await extract_fields_from_text(
            text=request.text,
            bounding_boxes=normalized_boxes,
            template=template,
        )

        # Convert to response format
        fields_dict: Dict[str, FieldData] = {}
        for field_key, field_data in result.get("fields", {}).items():
            fields_dict[field_key] = FieldData(
                value=field_data.get("value", ""),
                start=field_data.get("start"),
                end=field_data.get("end"),
                word_indexes=field_data.get("word_indexes", []),
            )

        logger.info(f"Successfully extracted {len(fields_dict)} fields")
        
        # Save structured fields to output_files/
        # Note: Original filename is not available in this endpoint, so we use a hash-based identifier
        # In production, consider adding filename as an optional parameter to the request
        try:
            import hashlib
            # Try to extract whisperHash from boundingBoxes if available
            filename = None
            if isinstance(normalized_boxes, dict):
                whisper_hash = normalized_boxes.get("whisperHash") or normalized_boxes.get("whisper_hash")
                if whisper_hash:
                    filename = f"file_{str(whisper_hash)[:12]}"
            
            # Fallback to text hash if no whisperHash found
            if not filename:
                text_hash = hashlib.md5(request.text.encode()).hexdigest()[:12]
                filename = f"extracted_{text_hash}"
            
            structured_path = get_output_path(filename, suffix="_structured", prefix="04")
            save_json(structured_path, {"fields": {k: v.dict() for k, v in fields_dict.items()}})
        except Exception as e:
            logger.warning(f"Failed to save structured fields: {e}")
            # Continue processing even if saving fails
        
        return ExtractFieldsResponse(fields=fields_dict)

    except FileNotFoundError as exc:
        error_msg = f"Template not found: {template_name}"
        logger.error(f"{error_msg}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_msg,
        ) from exc
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
