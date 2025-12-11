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

    NOTE: We no longer extract start/end from Groq. Groq only extracts VALUES.
    Word index mapping is done backend-side using LLMWhisperer highlight data.
    LLMWhisperer returns line-level bounding boxes, not word-level, so we map
    word_indexes to line_numbers for line-level highlighting.

    Args:
        text: Full layout-preserving text from LLMWhisperer
        bounding_boxes: Dictionary containing line_metadata (line-level bounding boxes)
        template: Template dictionary with field keys

    Returns:
        Dictionary with 'fields' key containing extracted field data:
        {
            "fields": {
                "field_key": {
                    "value": "...",
                    "word_indexes": [int, ...],
                    "line_numbers": [int, ...]  # Line numbers for highlighting
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

    # Build LLM prompt - only extract values, no positional metadata
    # Word index mapping will be done backend-side using LLMWhisperer highlight data
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

    # Parse LLM JSON response - only expects value and word_indexes
    parsed_response = _parse_llm_response(llm_response, template)

    # Map word_indexes to line_numbers using line_metadata
    # LLMWhisperer returns line-level bounding boxes, not word-level
    # We map word indexes to line numbers for line-level highlighting
    line_metadata = _extract_line_metadata(bounding_boxes)
    
    result_fields = {}
    for field_key, field_data in parsed_response.items():
        value = field_data.get("value")
        word_indexes = field_data.get("word_indexes", [])
        
        # Map word_indexes to line_numbers
        line_numbers = map_word_indexes_to_line_numbers(word_indexes, line_metadata, text)
        
        result_fields[field_key] = {
            "value": value if value is not None else "",
            "word_indexes": word_indexes,
            "line_numbers": line_numbers,
        }

    return {"fields": result_fields}


def _build_extraction_prompt(text: str, template: Dict[str, Any]) -> str:
    """
    Build prompt for LLM extraction.
    
    NOTE: We only extract VALUES, not positional metadata (start/end).
    Word index mapping is done backend-side using LLMWhisperer highlight data.
    This is because LLMWhisperer returns line-level bounding boxes, not word-level,
    so we map word indexes to line numbers for highlighting.
    """
    template_keys = list(template.keys())
    template_keys_json = json.dumps(template_keys, indent=2)

    prompt_parts = [
        "Extract field VALUES ONLY from the following layout-preserving text.",
        "",
        "Template field keys (extract ONLY these fields):",
        template_keys_json,
        "",
        "Layout-preserving text:",
        text,
        "",
        "Return STRICT JSON in this exact format:",
        "{",
        '  "field_key": {',
        '    "value": "extracted value or null if not found",',
        '    "word_indexes": [0, 1, 2, ...] or []',
        "  },",
        "  ...",
        "}",
        "",
        "Rules:",
        "- Never invent fields not in the template.",
        "- If a value is not found, return value=null, word_indexes=[].",
        "- word_indexes should be an array of word indexes (0-based) where the value appears.",
        "- Split the text on whitespace to determine word indexes.",
        "- For multi-word values, include all word indexes in the array.",
        "- If you cannot determine word indexes, return an empty array [].",
        "- Extract ONLY the value - do not compute character positions.",
        "- No explanations, no prose, only JSON.",
    ]

    return "\n".join(prompt_parts)


def _parse_llm_response(response_text: str, template: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse LLM JSON response safely.
    
    NOTE: We only expect value and word_indexes, not start/end.
    Positional metadata is no longer extracted from Groq.
    """
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
            result[field_key] = {"value": None, "word_indexes": []}
            continue

        # Extract value and word_indexes only
        word_indexes = field_data.get("word_indexes", [])
        if not isinstance(word_indexes, list):
            word_indexes = []
        else:
            # Ensure all are integers
            try:
                word_indexes = [int(idx) for idx in word_indexes if isinstance(idx, (int, str))]
            except (ValueError, TypeError):
                word_indexes = []

        result[field_key] = {
            "value": field_data.get("value"),
            "word_indexes": word_indexes,
        }

    # Ensure all template fields are present
    for key in template_keys:
        if key not in result:
            result[key] = {"value": None, "word_indexes": []}

    return result


def _create_empty_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Create empty field entries for all template keys."""
    return {
        key: {
            "value": "",
            "word_indexes": [],
        }
        for key in template.keys()
    }


def _extract_line_metadata(bounding_boxes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract line metadata from bounding boxes.
    
    LLMWhisperer returns line_metadata which contains line-level bounding boxes,
    not word-level. Each line has a line number and bounding box coordinates.
    """
    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        return []
    
    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    if isinstance(line_metadata, list):
        return line_metadata
    
    return []


def map_word_indexes_to_line_numbers(
    word_indexes: List[int], line_metadata: List[Dict[str, Any]], text: str
) -> List[int]:
    """
    Map word indexes to line numbers.
    
    LLMWhisperer returns line-level bounding boxes, not word-level.
    This function determines which line(s) contain the specified word indexes.
    
    Args:
        word_indexes: List of word indexes (0-based, from splitting text on whitespace)
        line_metadata: Line metadata from LLMWhisperer (contains line numbers and word ranges)
        text: The full text (split by lines to match line numbers)
        
    Returns:
        Sorted list of unique line numbers (1-based) that contain the word indexes
    """
    if not word_indexes or not line_metadata:
        return []
    
    # Split text into words for indexing
    words = text.split()
    
    # Build a mapping from word index to line number
    # We need to determine which line each word belongs to
    word_to_line: Dict[int, int] = {}
    
    # Process line metadata to find word ranges
    for line_data in line_metadata:
        if not isinstance(line_data, dict):
            continue
        
        line_number = line_data.get("line_no") or line_data.get("line_number") or line_data.get("line")
        if line_number is None:
            continue
        
        # Try to find word range for this line
        # LLMWhisperer may provide word_start and word_end, or we can infer from line position
        word_start = line_data.get("word_start") or line_data.get("start_word_index")
        word_end = line_data.get("word_end") or line_data.get("end_word_index")
        
        if word_start is not None and word_end is not None:
            # Map all words in this range to this line
            for word_idx in range(int(word_start), int(word_end) + 1):
                word_to_line[word_idx] = int(line_number)
        else:
            # Fallback: try to match by line text
            line_text = line_data.get("text", "")
            if line_text:
                # Find where this line's text appears in the full text
                # This is approximate but better than nothing
                line_words = line_text.split()
                if line_words:
                    # Try to find the first word of this line in the full word list
                    first_word = line_words[0]
                    for idx, word in enumerate(words):
                        if word == first_word:
                            # Map words of this line
                            for i, _ in enumerate(line_words):
                                if idx + i < len(words):
                                    word_to_line[idx + i] = int(line_number)
                            break
    
    # If we couldn't build word-to-line mapping, try alternative approach
    if not word_to_line:
        # Fallback: split text by lines and assign word indexes sequentially
        lines = text.split("\n")
        word_idx = 0
        for line_num, line in enumerate(lines, start=1):
            line_words = line.split()
            for _ in line_words:
                word_to_line[word_idx] = line_num
                word_idx += 1
    
    # Map the requested word indexes to line numbers
    line_numbers = set()
    for word_idx in word_indexes:
        if word_idx in word_to_line:
            line_numbers.add(word_to_line[word_idx])
    
    return sorted(list(line_numbers))


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
