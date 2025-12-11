import logging
from typing import Any, Dict, Optional

from utils.file_saver import get_output_path, save_json

logger = logging.getLogger(__name__)


def format_upload_response(extraction_result: Dict[str, Any]) -> Dict[str, Any]:
    if not extraction_result:
        raise ValueError("Extraction result cannot be empty.")

    file_name = extraction_result.get("file_name", "unknown")
    result_text = extraction_result.get("result_text")
    whisper_hash = extraction_result.get("whisper_hash")

    logger.info(f"Formatting response for '{file_name}': text_len={len(result_text) if result_text else 0}, hash={whisper_hash}")

    if not result_text:
        logger.error(f"No text returned for '{file_name}'. Full result: {extraction_result}")
        raise ValueError(f"No text returned for '{file_name}'.")
    if not whisper_hash:
        raise ValueError(f"Missing whisper hash for '{file_name}'.")

    # Save extracted text to output_files/
    try:
        text_path = get_output_path(file_name, suffix="_text", prefix="02")
        save_json(text_path, {"text": result_text, "whisperHash": whisper_hash})
    except Exception as e:
        logger.warning(f"Failed to save extracted text: {e}")
        # Continue processing even if saving fails

    # Save bounding boxes to output_files/
    bounding_boxes = _safe_get(extraction_result, "bounding_boxes")
    if bounding_boxes:
        try:
            bboxes_path = get_output_path(file_name, suffix="_bboxes", prefix="03")
            save_json(bboxes_path, {"boundingBoxes": bounding_boxes, "whisperHash": whisper_hash})
        except Exception as e:
            logger.warning(f"Failed to save bounding boxes: {e}")
            # Continue processing even if saving fails

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
