from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    """Extract fields using LLM and map values to citations (page, bbox, line_index)."""
    if not text or not text.strip():
        logger.warning("Empty text provided for extraction")
        return {"fields": _create_empty_fields(STANDARD_TEMPLATE)}

    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        logger.warning("Invalid or empty bounding boxes provided, extraction will proceed without citations")
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
            result_fields[field_key] = {"value": "", "citations": []}
            continue

        citations = _find_citations_for_value(str(value), line_metadata)
        result_fields[field_key] = {
            "value": str(value),
            "citations": citations,
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


def _find_citations_for_value(value: str, line_metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Find citations (page, bbox, line_index) for a value using multi-strategy matching.
    Strategies:
    1. Exact match (case-insensitive)
    2. Partial match (if value is long enough)
    3. Multi-line match (if value spans lines)
    """
    if not value or not line_metadata:
        return []

    target = value.strip().lower()
    if not target:
        return []

    matches: List[Dict[str, Any]] = []

    # Strategy 1: Exact Line Match (Case-Insensitive)
    for idx, entry in enumerate(line_metadata):
        text = (entry.get("text") or "").lower()
        if target in text:
            matches.append(_create_citation(entry, idx))

    if matches:
        return _deduplicate_citations(matches)

    # Strategy 2: Multi-line Match (for values split across lines)
    # We'll look for the value by concatenating lines
    # This is expensive, so we do a sliding window check
    # We assume the value might be split across 2-3 lines max usually
    
    # Clean target for multi-line check (remove extra spaces)
    clean_target = re.sub(r'\s+', '', target)
    
    for i in range(len(line_metadata)):
        # Check window of 1, 2, 3 lines
        for window_size in range(1, 4):
            if i + window_size > len(line_metadata):
                break
            
            window_lines = line_metadata[i : i + window_size]
            combined_text = "".join([(l.get("text") or "").lower() for l in window_lines])
            clean_combined = re.sub(r'\s+', '', combined_text)
            
            if clean_target in clean_combined:
                # Found a match spanning these lines
                for offset, line in enumerate(window_lines):
                    matches.append(_create_citation(line, i + offset))
                # If we found a match in this window, we can stop checking larger windows starting at i
                # But we might want to continue to find other occurrences? 
                # For now, let's just return the first good multi-line match set to avoid noise
                return _deduplicate_citations(matches)

    # Strategy 3: Fuzzy / Best Effort (if needed, but sticking to strict-ish for now to avoid false positives)
    # Could implement Levenshtein here if exact fails

    return _deduplicate_citations(matches)


def _create_citation(line_entry: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Create a standardized citation object from a line entry."""
    # Ensure bbox is always 4 integers
    raw_box = line_entry.get("raw_box") or [0, 0, 0, 0]
    if len(raw_box) < 4:
        raw_box = [0, 0, 0, 0]
        
    return {
        "page": line_entry.get("page", 1),
        "bbox": raw_box,
        "line_index": line_entry.get("line_index", index) # Prioritize explicit line_index
    }


def _deduplicate_citations(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate citations based on line_index."""
    seen = set()
    unique = []
    for cit in citations:
        line_idx = cit.get("line_index")
        if line_idx in seen:
            continue
        seen.add(line_idx)
        unique.append(cit)
    return unique


def _create_empty_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Create empty field entries for all template keys."""
    return {
        key: {
            "value": "",
            "citations": [],
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

