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
    """
    Normalize bounding boxes to a dict focused on line_metadata.

    Accepts:
      - None
      - list of objects
      - dict with "line_metadata": [...]
      - dict keyed by "1","2",...
    Returns:
      {"line_metadata": [ { line_number, text, raw_box, page, page_height, line_index }, ... ]}
    """
    if boxes is None:
        return {"line_metadata": []}

    # Already a normalized dict
    if isinstance(boxes, dict) and "line_metadata" in boxes and isinstance(boxes["line_metadata"], list):
        return {"line_metadata": boxes["line_metadata"]}

    out_lines: List[Dict[str, Any]] = []

    # If boxes is a list, assume it's directly line entries
    if isinstance(boxes, list):
        for i, entry in enumerate(boxes):
            if not isinstance(entry, dict):
                continue
            line_number = entry.get("line_number") or entry.get("line_index") or (i + 1)
            # raw_box discovery
            raw_box = None
            for candidate in ("raw_box", "raw", "bbox", "box"):
                if candidate in entry and entry[candidate]:
                    raw_box = entry[candidate]
                    break
            out_lines.append(
                {
                    "line_number": int(line_number),
                    "text": entry.get("text") or "",
                    "raw_box": raw_box,
                    "page": int(entry.get("page") or (raw_box[0] if isinstance(raw_box, list) and len(raw_box) >= 1 else 1) or 1),
                    "page_height": entry.get("page_height") or entry.get("pageHeight") or (raw_box[3] if isinstance(raw_box, list) and len(raw_box) >= 4 else 0),
                }
            )
        return {"line_metadata": out_lines}

    # If dict keyed by numeric strings
    numeric_items = []
    for k, v in boxes.items():
        try:
            idx = int(k)
        except Exception:
            continue
        numeric_items.append((idx, v))
    if numeric_items:
        numeric_items.sort(key=lambda x: x[0])
        for idx, obj in numeric_items:
            if not isinstance(obj, dict):
                continue
            raw_box = None
            for candidate in ("raw", "raw_box", "bbox", "box"):
                if candidate in obj and obj[candidate]:
                    raw_box = obj[candidate]
                    break
            if raw_box is None:
                for v in obj.values():
                    if isinstance(v, list) and len(v) >= 4:
                        raw_box = v
                        break
            page = int(obj.get("page") or (raw_box[0] if isinstance(raw_box, list) and len(raw_box) >= 1 else 1) or 1)
            if page == 0:
                page = 1
            page_height = obj.get("page_height") or obj.get("pageHeight") or (raw_box[3] if isinstance(raw_box, list) and len(raw_box) >= 4 else 0)
            out_lines.append(
                {
                    "line_number": int(idx),
                    "text": obj.get("text") or obj.get("line_text") or "",
                    "raw_box": raw_box,
                    "page": int(page),
                    "page_height": int(page_height or 0)
                }
            )
        return {"line_metadata": out_lines}

    logger.warning(f"Unexpected bounding boxes type in normalize: {type(boxes)}")
    return {"line_metadata": []}


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

    # normalize bounding boxes immediately
    bounding_boxes_norm = normalize_bounding_boxes(bounding_boxes)
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
    line_metadata = _extract_line_metadata(bounding_boxes_norm)

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


# rest of the file unchanged
def _build_extraction_prompt(text: str, template: Dict[str, Any]) -> str:
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
    if not value or not line_metadata:
        return []

    target = value.strip().lower()
    if not target:
        return []

    matches: List[Dict[str, Any]] = []

    # exact match
    for idx, entry in enumerate(line_metadata):
        text = (entry.get("text") or "").lower()
        if target in text:
            matches.append(_create_citation(entry, idx))

    if matches:
        return _deduplicate_citations(matches)

    # multi-line check (concatenate lines)
    import re
    clean_target = re.sub(r'\s+', '', target)
    for i in range(len(line_metadata)):
        for window_size in range(1, 4):
            if i + window_size > len(line_metadata):
                break
            window_lines = line_metadata[i : i + window_size]
            combined_text = "".join([(l.get("text") or "").lower() for l in window_lines])
            clean_combined = re.sub(r'\s+', '', combined_text)
            if clean_target in clean_combined:
                for offset, line in enumerate(window_lines):
                    matches.append(_create_citation(line, i + offset))
                return _deduplicate_citations(matches)

    return _deduplicate_citations(matches)


def _create_citation(line_entry: Dict[str, Any], index: int) -> Dict[str, Any]:
    raw_box = line_entry.get("raw_box") or [0, 0, 0, 0]
    if len(raw_box) < 4:
        raw_box = [0, 0, 0, 0]

    return {
        "page": int(line_entry.get("page", 1)),
        "bbox": [int(raw_box[0]), int(raw_box[1]), int(raw_box[2]), int(raw_box[3])],
        "line_index": int(line_entry.get("line_number") or line_entry.get("line_index") or index + 1)
    }


def _deduplicate_citations(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    return {
        key: {
            "value": "",
            "citations": [],
        }
        for key in template.keys()
    }


def _extract_line_metadata(bounding_boxes: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not bounding_boxes or not isinstance(bounding_boxes, dict):
        return []
    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    return line_metadata if isinstance(line_metadata, list) else []
