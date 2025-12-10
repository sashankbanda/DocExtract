import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.mapping_service import _load_template, extract_fields_from_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract-fields", tags=["extract-fields"])


class ExtractFieldsRequest(BaseModel):
    """Request model for field extraction."""

    text: str = Field(..., description="Layout-preserving text from LLMWhisperer")
    boundingBoxes: Dict[str, Any] = Field(..., description="Bounding box metadata from LLMWhisperer")
    templateName: Optional[str] = Field(
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

        # Extract fields using mapping service
        logger.info(f"Extracting fields from text (length: {len(request.text)})")
        result = await extract_fields_from_text(
            text=request.text,
            bounding_boxes=request.boundingBoxes,
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
