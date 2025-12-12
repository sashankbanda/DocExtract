from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field


class HighlightRequest(BaseModel):
    lineIndexes: List[int] = Field(..., description="Line indexes to highlight (1-based)")
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


def _convert_bboxes_to_list(bounding_boxes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Accept either:
      - { "line_metadata": [ {...}, ... ] }
      - { "1": {...}, "2": {...}, ... }
    and return a list of normalized entries with at least keys:
      - line_number (int), raw_box (list of 4), page, page_height, text (optional)
    """
    if not bounding_boxes:
        return []

    # case 1: already normalized
    if isinstance(bounding_boxes, dict) and "line_metadata" in bounding_boxes and isinstance(bounding_boxes["line_metadata"], list):
        return bounding_boxes["line_metadata"]

    # case 2: keyed dict of "1","2",...
    numeric_items = []
    for k, v in bounding_boxes.items():
        try:
            idx = int(k)
        except Exception:
            continue
        if isinstance(v, dict):
            numeric_items.append((idx, v))
    if numeric_items:
        numeric_items.sort(key=lambda x: x[0])
        out = []
        for idx, obj in numeric_items:
            # try to create a standard shape
            raw_box = None
            for candidate in ("raw", "raw_box", "bbox", "box"):
                if candidate in obj and obj[candidate]:
                    raw_box = obj[candidate]
                    break
            if raw_box is None:
                # fallback: search first list value
                for val in obj.values():
                    if isinstance(val, list) and len(val) >= 4:
                        raw_box = val
                        break
            entry = {
                "line_number": idx,
                "text": obj.get("text") or obj.get("line_text"),
                "raw_box": raw_box,
                "page": int(obj.get("page") or (raw_box[0] if isinstance(raw_box, list) and len(raw_box) >= 1 else 1) or 1),
                "page_height": obj.get("page_height") or obj.get("pageHeight") or (raw_box[3] if isinstance(raw_box, list) and len(raw_box) >= 4 else 0),
            }
            out.append(entry)
        return out

    # nothing recognized
    return []


@router.post("", response_model=List[HighlightResponse])
async def highlight(request: HighlightRequest) -> List[HighlightResponse]:
    if not request.lineIndexes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="lineIndexes cannot be empty.",
        )

    line_metadata = _convert_bboxes_to_list(request.boundingBoxes or {})
    if not isinstance(line_metadata, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid boundingBoxes payload: expected line list.",
        )

    results: List[HighlightResponse] = []

    for requested in request.lineIndexes:
        match = None
        for entry in line_metadata:
            # check a few possible keys
            ln = entry.get("line_number") or entry.get("line_index")
            try:
                if int(ln) == int(requested):
                    match = entry
                    break
            except Exception:
                continue

        if not match:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No bounding box found for line {requested}.",
            )

        raw_box = match.get("raw_box") or match.get("bbox") or match.get("box")
        if not isinstance(raw_box, list) or len(raw_box) < 4:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid raw_box for line {requested}.",
            )

        # LLMWhisperer raw_box is [page, base_y, height, page_height]
        page = int(match.get("page") or raw_box[0] or 1)
        if page == 0:
            page = 1

        base_y = float(raw_box[1])
        height = float(raw_box[2])
        page_height = float(match.get("page_height") or raw_box[3] or 0)

        # Many LLM outputs provide vertical-only boxes. We'll set x and width to 0 so UI can handle.
        x = 0.0
        width = 0.0
        y = base_y

        results.append(
            HighlightResponse(
                line_number=int(requested),
                page=page,
                x=x,
                y=y,
                width=width,
                height=height,
                page_height=page_height if page_height != 0 else None,
            )
        )

    return results
