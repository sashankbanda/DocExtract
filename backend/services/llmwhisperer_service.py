import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile, status
from unstract.llmwhisperer import LLMWhispererClientV2

from utils.file_saver import get_input_path, save_bytes

logger = logging.getLogger(__name__)

LLMWHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")

# Initialize LLMWhisperer SDK V2 client
llmw_client = LLMWhispererClientV2(
    base_url="https://llmwhisperer-api.us-central.unstract.com/api/v2",
    api_key=LLMWHISPERER_API_KEY,
)


async def process_upload_file(upload_file: UploadFile) -> Dict[str, Any]:
    """Upload a file to LLMWhisperer v2 and return text + line-level highlights."""
    if not LLMWHISPERER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLMWHISPERER_API_KEY is not configured.",
        )

    file_bytes = await upload_file.read()
    await upload_file.seek(0)

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{upload_file.filename}' is empty.",
        )

    # Save original file locally for reference and whisper call
    input_path = get_input_path(upload_file.filename or "unknown", prefix="01")
    if upload_file.filename:
        original_ext = Path(upload_file.filename).suffix
        if original_ext:
            input_path = input_path.with_suffix(original_ext)

    try:
        save_bytes(input_path, file_bytes)
        logger.info("Saved input file to %s", input_path)
    except Exception as exc:
        logger.warning(f"Failed to save input file: {exc}")
        # Fallback to a temp file so the whisper call still succeeds
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=input_path.suffix or ".bin")
        tmp.write(file_bytes)
        tmp.flush()
        tmp.close()
        input_path = Path(tmp.name)
        logger.info("Using temporary file for whisper call: %s", input_path)

    # Invoke whisper with synchronous wait and layout-preserving output
    try:
        whisper_result = llmw_client.whisper(
            file_path=str(input_path),
            wait_for_completion=True,
            wait_timeout=300,
            mode="form",
            output_mode="layout_preserving",
            add_line_nos=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLMWhisperer whisper failed: {exc}",
        ) from exc

    result_text = _extract_result_text(whisper_result)
    whisper_hash = _extract_whisper_hash(whisper_result)

    highlight_result = await get_highlight_data(whisper_hash)
    bounding_boxes = _normalize_line_metadata(highlight_result)

    return {
        "file_name": upload_file.filename or "unknown",
        "result_text": result_text,
        "whisper_hash": whisper_hash,
        "bounding_boxes": bounding_boxes,
        "pages": _extract_nested(whisper_result, "pages"),
    }


def _extract_result_text(data: Dict[str, Any]) -> str:
    """Try multiple paths to extract result_text from the response."""
    if data.get("result_text"):
        return data["result_text"]

    extraction = data.get("extraction", {})
    if isinstance(extraction, dict) and extraction.get("result_text"):
        return extraction["result_text"]

    inner = extraction.get("extraction", {})
    if isinstance(inner, dict) and inner.get("result_text"):
        return inner["result_text"]

    if data.get("text"):
        return data["text"]
    if extraction.get("text"):
        return extraction["text"]

    logger.warning(f"Could not find result_text in response. Keys: {list(data.keys())}")
    return ""


def _extract_nested(data: Dict[str, Any], key: str) -> Any:
    """Extract a key from nested response structure."""
    if data.get(key):
        return data[key]

    extraction = data.get("extraction", {})
    if isinstance(extraction, dict):
        if extraction.get(key):
            return extraction[key]
        inner = extraction.get("extraction", {})
        if isinstance(inner, dict) and inner.get(key):
            return inner[key]

    return None


def _extract_whisper_hash(payload: Dict[str, Any]) -> str:
    candidates = [
        payload.get("whisper_hash"),
        payload.get("hash"),
        payload.get("document_hash"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="LLMWhisperer response missing whisper hash.",
    )


def _normalize_line_metadata(highlight_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep only valid line-level metadata with required raw_box."""
    if not highlight_result or not isinstance(highlight_result, dict):
        logger.warning("Highlight data missing; returning empty line_metadata.")
        return {"line_metadata": []}

    raw_lines = highlight_result.get("line_metadata") or []
    if not isinstance(raw_lines, list):
        logger.warning("Highlight data did not contain line_metadata list; returning empty.")
        return {"line_metadata": []}

    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            continue

        text = (entry.get("text") or "").strip()
        if not text:
            continue

        raw_box = entry.get("raw_box") or entry.get("raw") or entry.get("bbox") or entry.get("box")
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

        line_number = entry.get("line_number") or entry.get("line_no") or entry.get("line") or (idx + 1)
        page = entry.get("page") or entry.get("page_number") or box_ints[0] or 1
        page_height = entry.get("page_height") or entry.get("pageHeight") or box_ints[3]

        normalized.append(
            {
                "line_number": int(line_number),
                "text": text,
                "raw_box": [int(box_ints[0]), int(box_ints[1]), int(box_ints[2]), int(box_ints[3])],
                "page": int(page),
                "page_height": int(page_height) if page_height is not None else None,
            }
        )

    return {"line_metadata": normalized}


async def get_highlight_data(whisper_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch highlight bounding boxes using LLMWhisperer SDK V2 for a fixed line range."""
    try:
        logger.info("Requesting highlight data via SDK for lines 1-5000")
        return llmw_client.get_highlight_data(
            whisper_hash=whisper_hash,
            lines="1-5000",
        )
    except Exception as exc:
        logger.error(f"Highlight SDK error: {exc}")
        return None
