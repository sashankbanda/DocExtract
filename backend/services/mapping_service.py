from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from services.groq_service import GroqService

logger = logging.getLogger(__name__)

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


STANDARD_TEMPLATE = _load_template("standard_template")


def normalize_bounding_boxes(boxes: Dict[str, Any] | List[Any] | None) -> Dict[str, Any]:
    """Normalize bounding boxes to a dict focused on line metadata."""
    if boxes is None:
        return {}

    if isinstance(boxes, list):
        return {"line_metadata": boxes}

    if isinstance(boxes, dict):
        return boxes

    logger.warning(f"Unexpected bounding boxes type: {type(boxes)}, returning empty dict")
    return {}


async def extract_fields_from_text(
    text: str, bounding_boxes: Dict[str, Any]
) -> Dict[str, Any]:
    """Extract fields using LLM and map values to line indexes."""
    if not text or not text.strip():
        logger.warning("Empty text provided for extraction")
        return {"fields": _create_empty_fields(STANDARD_TEMPLATE)}

    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        logger.warning("Invalid or empty bounding boxes provided, extraction will proceed without line indexes")
        bounding_boxes = {}

    prompt = _build_extraction_prompt(text, STANDARD_TEMPLATE)

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
                return {"fields": _create_empty_fields(STANDARD_TEMPLATE)}
            logger.warning(f"LLM request failed (attempt {attempt + 1}), retrying...")

    if not llm_response:
        return {"fields": _create_empty_fields(STANDARD_TEMPLATE)}

    parsed_response = _parse_llm_response(llm_response, STANDARD_TEMPLATE)
    line_metadata = _extract_line_metadata(bounding_boxes)

    result_fields: Dict[str, Dict[str, Any]] = {}
    for field_key, field_data in parsed_response.items():
        value = field_data.get("value")
        if value is None or value == "":
            result_fields[field_key] = {"value": "", "line_indexes": []}
            continue

        line_indexes = _find_line_indexes_for_value(str(value), line_metadata)
        result_fields[field_key] = {
            "value": str(value),
            "line_indexes": line_indexes,
        }

    return {"fields": result_fields}


def _build_extraction_prompt(text: str, template: Dict[str, Any]) -> str:
    """Build prompt for LLM extraction (values only)."""
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
        '    "value": "extracted value or null if not found"',
        "  },",
        "  ...",
        "}",
        "",
        "Rules:",
        "- Never invent fields not in the template.",
        "- If a value is not found, return value=null.",
        "- Extract ONLY the value - no positions, offsets, or indexes.",
        "- Return the exact value as it appears in the text.",
        "- No explanations, no prose, only JSON.",
    ]

    return "\n".join(prompt_parts)


def _parse_llm_response(response_text: str, template: Dict[str, Any]) -> Dict[str, Any]:
    """Parse LLM JSON response safely (values only)."""
    cleaned = response_text.strip()

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

    result = {}
    template_keys = set(template.keys())

    for field_key, field_data in parsed.items():
        if field_key not in template_keys:
            logger.warning(f"Ignoring field not in template: {field_key}")
            continue

        if not isinstance(field_data, dict):
            logger.warning(f"Invalid field data format for {field_key}: {type(field_data)}")
            result[field_key] = {"value": None}
            continue

        result[field_key] = {
            "value": field_data.get("value"),
        }

    for key in template_keys:
        if key not in result:
            result[key] = {"value": None}

    return result


def _find_line_indexes_for_value(value: str, line_metadata: List[Dict[str, Any]]) -> List[int]:
    """Find line numbers whose text contains the given value (case-insensitive substring match)."""
    if not value or not line_metadata:
        return []

    target = value.strip().lower()
    if not target:
        return []

    matches: List[int] = []
    for idx, entry in enumerate(line_metadata):
        if not isinstance(entry, dict):
            continue

        line_number = entry.get("line_number") or entry.get("line_no") or entry.get("line") or (idx + 1)
        text = entry.get("text") or ""
        if not isinstance(text, str):
            continue

        if target in text.lower():
            matches.append(int(line_number))

    seen = set()
    unique_matches = []
    for line_num in matches:
        if line_num in seen:
            continue
        seen.add(line_num)
        unique_matches.append(line_num)

    return unique_matches


def _create_empty_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Create empty field entries for all template keys."""
    return {
        key: {
            "value": "",
            "line_indexes": [],
        }
        for key in template.keys()
    }


def _extract_line_metadata(bounding_boxes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract line metadata from bounding boxes."""
    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        return []

    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    if isinstance(line_metadata, list):
        return line_metadata

    return []
