from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.mapping_service import merge_word_bounding_boxes


class HighlightRequest(BaseModel):
    wordIndexes: List[int] = Field(..., description="Word indexes to highlight")
    boundingBoxes: Dict[str, Any] = Field(..., description="Bounding box metadata returned by LLMWhisperer")


class HighlightResponse(BaseModel):
    page: int
    x: float
    y: float
    width: float
    height: float


router = APIRouter(prefix="/highlight", tags=["highlight"])


@router.post("", response_model=List[HighlightResponse])
async def highlight(request: HighlightRequest) -> List[HighlightResponse]:
    if not request.wordIndexes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wordIndexes cannot be empty.",
        )

    try:
        merged = merge_word_bounding_boxes(
            word_indexes=request.wordIndexes,
            bounding_box_payload=request.boundingBoxes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return [HighlightResponse(**item) for item in merged]
