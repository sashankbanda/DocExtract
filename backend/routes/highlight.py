from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field


class HighlightRequest(BaseModel):
    lineIndexes: List[int] = Field(..., description="Line indexes to highlight")
    boundingBoxes: Dict[str, Any] = Field(..., description="Bounding box metadata returned by LLMWhisperer")


class HighlightResponse(BaseModel):
    line_number: int
    page: int
    x: float
    y: float
    width: float
    height: float
    page_height: float | None = None


router = APIRouter(prefix="/highlight", tags=["highlight"])


@router.post("", response_model=List[HighlightResponse])
async def highlight(request: HighlightRequest) -> List[HighlightResponse]:
    if not request.lineIndexes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lineIndexes cannot be empty.",
        )

    bounding_boxes = request.boundingBoxes or {}
    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines") or []
    if not isinstance(line_metadata, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid boundingBoxes payload: expected line_metadata list.",
        )

    results: List[HighlightResponse] = []

    for line_idx in request.lineIndexes:
        match = None
        for entry in line_metadata:
            if not isinstance(entry, dict):
                continue
            line_number = entry.get("line_number") or entry.get("line_no") or entry.get("line")
            if line_number is None:
                continue
            if int(line_number) == int(line_idx):
                match = entry
                break

        if not match:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No bounding box found for line {line_idx}.",
            )

        raw_box = match.get("raw_box") or match.get("raw") or match.get("bbox") or match.get("box")
        if not isinstance(raw_box, list) or len(raw_box) < 4:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid raw_box for line {line_idx}.",
            )

        page = int(match.get("page") or 1)
        x, y, width, height = [float(raw_box[i]) for i in range(4)]
        page_height = match.get("page_height") or match.get("pageHeight")

        results.append(
            HighlightResponse(
                line_number=int(line_idx),
                page=page,
                x=x,
                y=y,
                width=width,
                height=height,
                page_height=float(page_height) if page_height is not None else None,
            )
        )

    return results
