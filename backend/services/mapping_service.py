from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from services.groq_service import GroqService

logger = logging.getLogger(__name__)

MERGE_GAP_RATIO = 0.5
LINE_ALIGNMENT_RATIO = 0.6

# Load standard template at module import
_TEMPLATE_CACHE: Dict[str, Dict[str, Any]] = {}
_TEMPLATE_DIR = Path(__file__).parent.parent


def _load_template(template_name: str = "standard_template") -> Dict[str, Any]:
    """Load template JSON file from backend directory."""
    if template_name in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[template_name]

    template_path = _TEMPLATE_DIR / f"{template_name}.json"
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)
        _TEMPLATE_CACHE[template_name] = template
        logger.info(f"Loaded template: {template_name}")
        return template
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in template file {template_path}: {exc}") from exc


# Load standard template at module import
STANDARD_TEMPLATE = _load_template("standard_template")


def normalize_bounding_boxes(boxes: Dict[str, Any] | List[Any] | None) -> Dict[str, Any]:
    """
    Normalize bounding boxes to a consistent dictionary format.

    Args:
        boxes: Bounding boxes as dict, list, or None

    Returns:
        Normalized dictionary with string keys
    """
    if boxes is None:
        return {}
    
    if isinstance(boxes, list):
        # Convert list to dict with numeric string keys
        return {str(i): box for i, box in enumerate(boxes)}
    
    if isinstance(boxes, dict):
        return boxes
    
    # Fallback: return empty dict for unexpected types
    logger.warning(f"Unexpected bounding boxes type: {type(boxes)}, returning empty dict")
    return {}


async def extract_fields_from_text(
    text: str, bounding_boxes: Dict[str, Any], template: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract fields from layout-preserving text using LLM.

    Args:
        text: Full layout-preserving text from LLMWhisperer
        bounding_boxes: Dictionary mapping word indexes to bounding box data
        template: Template dictionary with field keys

    Returns:
        Dictionary with 'fields' key containing extracted field data:
        {
            "fields": {
                "field_key": {
                    "value": "...",
                    "start": int | None,
                    "end": int | None,
                    "word_indexes": [int, ...]
                }
            }
        }
    """
    if not text or not text.strip():
        logger.warning("Empty text provided for extraction")
        return {"fields": _create_empty_fields(template)}

    # Handle empty or invalid bounding boxes gracefully
    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        logger.warning("Invalid or empty bounding boxes provided, extraction will proceed without word indexes")
        bounding_boxes = {}

    # Build LLM prompt
    prompt = _build_extraction_prompt(text, template)

    # Call Groq service
    groq_service = GroqService()
    max_retries = 2
    llm_response = None

    for attempt in range(max_retries):
        try:
            llm_response = await groq_service.extract(prompt)
            break
        except Exception as exc:
            if attempt == max_retries - 1:
                logger.error(f"Failed to get LLM response after {max_retries} attempts: {exc}")
                return {"fields": _create_empty_fields(template)}
            logger.warning(f"LLM request failed (attempt {attempt + 1}), retrying...")

    if not llm_response:
        return {"fields": _create_empty_fields(template)}

    # Parse LLM JSON response
    parsed_response = _parse_llm_response(llm_response, template)

    # Convert start/end indexes to word_indexes arrays
    result_fields = {}
    for field_key, field_data in parsed_response.items():
        start = field_data.get("start")
        end = field_data.get("end")
        value = field_data.get("value")

        # Generate word_indexes array from start/end
        # Only populate if bounding_boxes are available and valid
        word_indexes = []
        if bounding_boxes and start is not None and end is not None:
            # Ensure start <= end and both are integers
            try:
                start_int = int(start)
                end_int = int(end)
                if start_int <= end_int:
                    word_indexes = list(range(start_int, end_int + 1))
            except (ValueError, TypeError):
                logger.warning(f"Invalid start/end for field {field_key}: start={start}, end={end}")

        result_fields[field_key] = {
            "value": value if value is not None else "",
            "start": start,
            "end": end,
            "word_indexes": word_indexes,
        }

    return {"fields": result_fields}


def _build_extraction_prompt(text: str, template: Dict[str, Any]) -> str:
    """Build prompt for LLM extraction."""
    template_keys = list(template.keys())
    template_keys_json = json.dumps(template_keys, indent=2)

    # Split text to show word indexing
    words = text.split()
    word_count = len(words)

    prompt_parts = [
        "Extract field values from the following layout-preserving text.",
        "",
        "Template field keys (extract ONLY these fields):",
        template_keys_json,
        "",
        f"Layout-preserving text (contains {word_count} words when split on whitespace):",
        text,
        "",
        "Return STRICT JSON in this exact format:",
        "{",
        '  "field_key": {',
        '    "value": "extracted value or null if not found",',
        '    "start": word_index_start or null,',
        '    "end": word_index_end or null',
        "  },",
        "  ...",
        "}",
        "",
        "Rules:",
        "- Never invent fields not in the template.",
        "- If a value is not found, return value=null, start=null, end=null.",
        "- Word indexes are 0-based: first word = 0, second word = 1, etc.",
        f"- Valid word index range: 0 to {word_count - 1} (inclusive).",
        "- start and end must refer to word indexes when the text is split on whitespace.",
        "- For multi-word values, start is the first word index and end is the last word index (inclusive).",
        "- No explanations, no prose, only JSON.",
    ]

    return "\n".join(prompt_parts)


def _parse_llm_response(response_text: str, template: Dict[str, Any]) -> Dict[str, Any]:
    """Parse LLM JSON response safely."""
    cleaned = response_text.strip()

    # Remove markdown code blocks if present
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part and part not in {"json", "JSON"}:
                cleaned = part
                break

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse LLM response as JSON: {exc}")
        logger.debug(f"Response text: {response_text[:500]}")
        return _create_empty_fields(template)

    if not isinstance(parsed, dict):
        logger.error(f"LLM response is not a dictionary: {type(parsed)}")
        return _create_empty_fields(template)

    # Validate and normalize response
    result = {}
    template_keys = set(template.keys())

    for field_key, field_data in parsed.items():
        # Only include fields that are in the template
        if field_key not in template_keys:
            logger.warning(f"Ignoring field not in template: {field_key}")
            continue

        if not isinstance(field_data, dict):
            logger.warning(f"Invalid field data format for {field_key}: {type(field_data)}")
            result[field_key] = {"value": None, "start": None, "end": None}
            continue

        result[field_key] = {
            "value": field_data.get("value"),
            "start": field_data.get("start"),
            "end": field_data.get("end"),
        }

    # Ensure all template fields are present
    for key in template_keys:
        if key not in result:
            result[key] = {"value": None, "start": None, "end": None}

    return result


def _create_empty_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Create empty field entries for all template keys."""
    return {
        key: {
            "value": "",
            "start": None,
            "end": None,
            "word_indexes": [],
        }
        for key in template.keys()
    }


# Existing functions for bounding box merging (kept for backward compatibility)
def merge_word_bounding_boxes(
    *, word_indexes: Iterable[int], bounding_box_payload: Dict[str, Any]
) -> List[Dict[str, float]]:
    """Merge word bounding boxes for highlighting."""
    if bounding_box_payload is None:
        raise ValueError("boundingBoxes payload cannot be None.")

    index_lookup = _build_index_lookup(bounding_box_payload)

    unique_indexes: List[int] = []
    seen = set()
    for idx in word_indexes:
        if idx in seen:
            continue
        seen.add(idx)
        unique_indexes.append(int(idx))

    if not unique_indexes:
        raise ValueError("wordIndexes produced no unique indexes to map.")

    selected_boxes: Dict[int, List[Dict[str, float]]] = defaultdict(list)

    for idx in unique_indexes:
        box = index_lookup.get(idx)
        if not box:
            raise ValueError(f"No bounding box found for word index {idx}.")
        selected_boxes[int(box["page"])].append(box)

    merged_results: List[Dict[str, float]] = []
    for page, boxes in selected_boxes.items():
        merged_results.extend(_merge_boxes_for_page(page, boxes))

    return merged_results


def _build_index_lookup(payload: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
    """Build lookup dictionary for word indexes to bounding boxes."""
    lookup: Dict[int, Dict[str, float]] = {}

    words = payload.get("words")
    if isinstance(words, list):
        for word in words:
            _add_word_to_lookup(lookup, word)

    pages = payload.get("pages")
    if isinstance(pages, list):
        for page in pages:
            for word in page.get("words", []):
                _add_word_to_lookup(lookup, word, default_page=page.get("page", page.get("index")))

    if not lookup:
        raise ValueError("Bounding box payload does not contain recognisable word data.")

    return lookup


def _add_word_to_lookup(
    lookup: Dict[int, Dict[str, float]],
    word_payload: Dict[str, Any],
    default_page: Any = None,
) -> None:
    """Add a word to the lookup dictionary."""
    if not isinstance(word_payload, dict):
        return

    index = word_payload.get("index")
    if index is None:
        return

    bbox = word_payload.get("bbox") or word_payload.get("bounding_box") or {}
    if not bbox:
        return

    page = word_payload.get("page", default_page)
    if page is None:
        return

    x1, y1, x2, y2 = _normalise_box_coordinates(bbox)
    lookup[int(index)] = {
        "page": float(page),
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }


def _normalise_box_coordinates(bbox: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """Normalize bounding box coordinates to x1, y1, x2, y2 format."""
    if {"x", "y", "width", "height"}.issubset(bbox):
        x1 = float(bbox["x"])
        y1 = float(bbox["y"])
        return x1, y1, x1 + float(bbox["width"]), y1 + float(bbox["height"])

    if {"left", "top", "right", "bottom"}.issubset(bbox):
        return (
            float(bbox["left"]),
            float(bbox["top"]),
            float(bbox["right"]),
            float(bbox["bottom"]),
        )

    raise ValueError("Unsupported bounding box coordinate format.")


def _merge_boxes_for_page(page: int, boxes: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Merge bounding boxes for a single page."""
    if not boxes:
        return []

    sorted_boxes = sorted(boxes, key=lambda b: (b["y"], b["x"]))
    merged: List[Dict[str, float]] = []

    for box in sorted_boxes:
        if not merged:
            merged.append({**box, "page": page})
            continue

        last = merged[-1]
        if _boxes_should_merge(last, box):
            merged[-1] = _merge_two_boxes(last, box)
        else:
            merged.append({**box, "page": page})

    return merged


def _boxes_should_merge(first: Dict[str, float], second: Dict[str, float]) -> bool:
    """Check if two boxes should be merged."""
    same_page = int(first["page"]) == int(second["page"])
    if not same_page:
        return False

    vertical_overlap = abs(first["y"] - second["y"]) <= max(first["height"], second["height"]) * LINE_ALIGNMENT_RATIO
    horizontal_gap = second["x"] - (first["x"] + first["width"])

    return vertical_overlap and horizontal_gap <= max(first["width"], second["width"]) * MERGE_GAP_RATIO


def _merge_two_boxes(first: Dict[str, float], second: Dict[str, float]) -> Dict[str, float]:
    """Merge two bounding boxes into one."""
    x1 = min(first["x"], second["x"])
    y1 = min(first["y"], second["y"])
    x2 = max(first["x"] + first["width"], second["x"] + second["width"])
    y2 = max(first["y"] + first["height"], second["y"] + second["height"])

    return {
        "page": first["page"],
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }
