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
            bboxes_path = get_output_path(file_name, suffix="_bboxes", prefix="03")
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
    """
    lines = result_text.split("\n")
    formatted_lines: List[Dict[str, Any]] = []

    raw_line_metadata = None
    if isinstance(bounding_boxes, dict):
        raw_line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    elif isinstance(bounding_boxes, list):
        raw_line_metadata = bounding_boxes

    if raw_line_metadata and isinstance(raw_line_metadata, list):
        for idx, line_data in enumerate(raw_line_metadata):
            if not isinstance(line_data, dict):
                continue

            line_number = line_data.get("line_number") or line_data.get("line_no") or line_data.get("line") or (idx + 1)
            text = line_data.get("text") or (lines[line_number - 1] if 0 <= line_number - 1 < len(lines) else "")
            raw_box = line_data.get("raw_box") or line_data.get("raw") or line_data.get("bbox") or line_data.get("box")

            if isinstance(raw_box, list) and len(raw_box) >= 4:
                box_vals = raw_box[:4]
            elif isinstance(raw_box, dict):
                box_vals = [
                    raw_box.get("page") or raw_box.get("x") or raw_box.get("left") or 0,
                    raw_box.get("base_y") or raw_box.get("y") or raw_box.get("top") or 0,
                    raw_box.get("height") or raw_box.get("h") or 0,
                    raw_box.get("page_height") or raw_box.get("pageHeight") or 0,
                ]
            else:
                continue

            try:
                box_ints = [int(float(v)) for v in box_vals]
            except (TypeError, ValueError):
                continue

            if len(box_ints) < 4 or any(v is None for v in box_ints):
                continue
            if all(v == 0 for v in box_ints):
                continue

            formatted_lines.append(
                {
                    "line_number": int(line_number),
                    "text": text,
                    "raw_box": [int(box_ints[0]), int(box_ints[1]), int(box_ints[2]), int(box_ints[3])],
                    "page": int(line_data.get("page") or 1),
                    "page_height": line_data.get("page_height") or line_data.get("pageHeight") or box_ints[3],
                }
            )

    return {
        "whisperHash": whisper_hash,
        "line_metadata": formatted_lines,
    }
