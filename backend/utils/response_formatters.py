import logging
from typing import Any, Dict, List, Optional

from utils.file_saver import get_output_path, save_json, save_text

logger = logging.getLogger(__name__)


def format_upload_response(extraction_result: Dict[str, Any]) -> Dict[str, Any]:
    if not extraction_result:
        raise ValueError("Extraction result cannot be empty.")

    file_name = extraction_result.get("file_name", "unknown")
    result_text = extraction_result.get("result_text")
    whisper_hash = extraction_result.get("whisper_hash")

    logger.info(
        f"Formatting response for '{file_name}': text_len={len(result_text) if result_text else 0}, hash={whisper_hash}"
    )

    if not result_text:
        logger.error(f"No text returned for '{file_name}'. Full result: {extraction_result}")
        raise ValueError(f"No text returned for '{file_name}'.")
    if not whisper_hash:
        raise ValueError(f"Missing whisper hash for '{file_name}'.")

    try:
        text_path = get_output_path(file_name, suffix="_text", prefix="02", extension="txt")
        save_text(text_path, result_text)
        logger.info("Saved extracted text to %s", text_path)
    except Exception as e:
        logger.warning(f"Failed to save extracted text: {e}")

    bounding_boxes = _safe_get(extraction_result, "bounding_boxes")
    if bounding_boxes:
        try:
            bboxes_path = get_output_path(file_name, suffix="_bboxes", prefix="03", extension="json")
            formatted_bboxes = _format_bounding_boxes_for_save(
                bounding_boxes, result_text, whisper_hash
            )
            save_json(bboxes_path, formatted_bboxes)
            logger.info("Saved bounding boxes to %s", bboxes_path)
        except Exception as e:
            logger.warning(f"Failed to save bounding boxes: {e}")

    return {
        "fileName": file_name,
        "text": result_text,
        "whisperHash": whisper_hash,
        "boundingBoxes": bounding_boxes,
        "pages": _safe_get(extraction_result, "pages"),
    }


def _safe_get(source: Dict[str, Any], key: str) -> Optional[Any]:
    value = source.get(key)
    return value if value not in ({}, []) else None


def _format_bounding_boxes_for_save(
    bounding_boxes: Any, result_text: str, whisper_hash: str
) -> Dict[str, Any]:
    """
    Format bounding boxes for saving with line-level metadata only.
    Accepts:
      - dict with 'line_metadata' list
      - dict keyed by '1','2',... (LLMWhisperer original shape)
      - list of line objects
    Output shape:
    {
      "whisperHash": "...",
      "line_metadata": [
         { "line_number": int, "text": str, "raw_box": [p,y,h,page_h], "page": int, "page_height": int }
      ]
    }
    """
    lines = result_text.split("\n")
    formatted_lines: List[Dict[str, Any]] = []

    # If it's already a friendly dict...
    raw_line_metadata = None
    if isinstance(bounding_boxes, dict):
        if "line_metadata" in bounding_boxes and isinstance(bounding_boxes["line_metadata"], list):
            raw_line_metadata = bounding_boxes["line_metadata"]
        else:
            # maybe keyed by "1", "2", ...
            # convert to list preserving numeric order
            # include only entries that are dict-like
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
                raw_line_metadata = [v for _, v in numeric_items]

    elif isinstance(bounding_boxes, list):
        raw_line_metadata = bounding_boxes

    if not raw_line_metadata:
        # nothing to save: return empty list
        return {"whisperHash": whisper_hash, "line_metadata": []}

    for idx, line_data in enumerate(raw_line_metadata):
        if not isinstance(line_data, dict):
            continue

        # Determine line_number
        line_number = (
            line_data.get("line_number")
            or line_data.get("line_index")
            or line_data.get("line_no")
            or line_data.get("line")
            or (idx + 1)
        )

        # text fallback from the extracted text lines (1-based)
        try:
            ln_idx = int(line_number) - 1
            text_val = line_data.get("text") or (lines[ln_idx] if 0 <= ln_idx < len(lines) else "")
        except Exception:
            text_val = line_data.get("text") or ""

        # raw_box may appear under several keys
        raw_box = None
        for candidate in ("raw_box", "raw", "bbox", "box"):
            if candidate in line_data and line_data[candidate]:
                raw_box = line_data[candidate]
                break

        # If raw_box is dict, try mapping keys
        if isinstance(raw_box, dict):
            page = int(raw_box.get("page", 1) or 1)
            base_y = int(raw_box.get("base_y", raw_box.get("y", 0) or 0))
            height = int(raw_box.get("height", raw_box.get("h", 0) or 0))
            page_height = int(raw_box.get("page_height", raw_box.get("pageHeight", 0) or 0))
            box_vals = [page, base_y, height, page_height]
        elif isinstance(raw_box, list) and len(raw_box) >= 4:
            try:
                box_vals = [int(float(v)) for v in raw_box[:4]]
            except Exception:
                continue
        else:
            # no usable box
            continue

        # ignore placeholder all zeros
        if all(v == 0 for v in box_vals):
            continue

        page_val = int(line_data.get("page") or box_vals[0] or 1)
        if page_val == 0:
            page_val = 1

        page_height_val = int(line_data.get("page_height") or box_vals[3] or 0)

        formatted_lines.append(
            {
                "line_number": int(line_number),
                "text": text_val,
                "raw_box": [int(box_vals[0]), int(box_vals[1]), int(box_vals[2]), int(box_vals[3])],
                "page": int(page_val),
                "page_height": int(page_height_val),
            }
        )

    return {"whisperHash": whisper_hash, "line_metadata": formatted_lines}
