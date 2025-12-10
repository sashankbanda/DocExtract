from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.groq_service import perform_template_extraction


class ExtractFieldsRequest(BaseModel):
    fullText: str = Field(..., description="Complete extracted text from LLMWhisperer")
    wordList: List[Dict[str, Any]] = Field(..., description="List of word metadata with indexes")
    templateJson: Dict[str, Any] = Field(..., description="Template describing the fields to extract")


class ExtractedField(BaseModel):
    key: str
    value: str
    word_indexes: List[int]


router = APIRouter(prefix="/extract-fields", tags=["extract-fields"])


@router.post("", response_model=List[ExtractedField])
async def extract_fields(request: ExtractFieldsRequest) -> List[ExtractedField]:
    try:
        extraction = await perform_template_extraction(
            full_text=request.fullText,
            word_list=request.wordList,
            template_json=request.templateJson,
        )
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
            detail=f"Template extraction failed: {exc}",
        ) from exc

    if not isinstance(extraction, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected response format from template extraction service.",
        )

    return [ExtractedField(**item) for item in extraction]
