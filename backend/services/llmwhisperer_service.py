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


# ---------------------------------------------------------
# PROCESS FILE UPLOAD
# ---------------------------------------------------------

async def process_upload_file(upload_file: UploadFile) -> Dict[str, Any]:
    if not LLMWHISPERER_API_KEY:
        raise HTTPException(500, "LLMWHISPERER_API_KEY is not configured.")

    file_bytes = await upload_file.read()
    await upload_file.seek(0)

    if not file_bytes:
        raise HTTPException(400, f"{upload_file.filename} is empty")

    # Save input
    input_path = get_input_path(upload_file.filename or "file", prefix="01")
    ext = Path(upload_file.filename).suffix
    if ext:
        input_path = input_path.with_suffix(ext)

    try:
        save_bytes(input_path, file_bytes)
    except Exception:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(file_bytes)
        tmp.close()
        input_path = Path(tmp.name)

    # ---- 1. Run whisper with layout output ----
    try:
        whisper_result = llmw_client.whisper(
            file_path=str(input_path),
            wait_for_completion=True,
            wait_timeout=300,
            mode="form",
            output_mode="layout_preserving",
            add_line_nos=True,
        )
    except Exception as exc:
        raise HTTPException(502, f"LLMWhisperer whisper failed: {exc}")

    original_text = _extract_result_text(whisper_result)
    whisper_hash = _extract_whisper_hash(whisper_result)
    logger.info(f"Extracted whisper_hash: {whisper_hash}")

    # ---- 2. Fetch highlights (real bounding boxes) ----
    highlight_data = await get_highlight_data(whisper_hash)
    if highlight_data:
        fkey = list(highlight_data.keys())[0]
        logger.info(f"Highlight sample: {highlight_data[fkey]}")
    else:
        logger.warning("Highlight returned empty.")

    # ---- 3. Normalize and reconstruct text ----
    norm = _normalize_line_metadata(highlight_data)
    reconstructed_text = norm["text"]
    bounding_boxes = norm["bounding_boxes"]

    final_text = reconstructed_text if reconstructed_text.strip() else original_text

    return {
        "file_name": upload_file.filename,
        "result_text": final_text,
        "whisper_hash": whisper_hash,
        "bounding_boxes": bounding_boxes,
        "pages": _extract_nested(whisper_result, "pages"),
    }


# ---------------------------------------------------------
# RESULT PARSERS
# ---------------------------------------------------------

def _extract_result_text(data: Dict[str, Any]) -> str:
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

    logger.warning("Could not find result_text in response.")
    return ""


def _extract_nested(data: Dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]

    extraction = data.get("extraction", {})
    if key in extraction:
        return extraction[key]

    inner = extraction.get("extraction", {})
    if key in inner:
        return inner[key]

    return None


def _extract_whisper_hash(payload: Dict[str, Any]) -> str:
    for k in ["whisper_hash", "hash", "document_hash"]:
        if payload.get(k):
            return str(payload[k])

    raise HTTPException(502, "LLMWhisperer response missing whisper_hash.")


# ---------------------------------------------------------
# LINE NORMALIZATION
# ---------------------------------------------------------

def _normalize_line_metadata(highlight_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not highlight_result:
        return {"bounding_boxes": {"line_metadata": []}, "text": ""}

    raw_lines = []

    # highlight_result is dict keyed by line numbers: "1": {...}, "2": {...}
    for key, entry in highlight_result.items():
        if not isinstance(entry, dict):
            continue

        text = (entry.get("text") or "").strip()
        if not text:
            continue

        raw_box = entry.get("raw") or entry.get("raw_box") or entry.get("bbox")
        if not raw_box:
            continue

        if isinstance(raw_box, list) and len(raw_box) >= 4:
            page, base_y, height, page_height = raw_box[:4]
        else:
            continue

        # Ignore lines where the bbox is dummy / placeholder
        if all(int(float(v)) == 0 for v in [page, base_y, height, page_height]):
            continue

        raw_lines.append({
            "text": text,
            "page": int(float(page)),
            "base_y": int(float(base_y)),
            "height": int(float(height)),
            "page_height": int(float(page_height)),
        })

    if not raw_lines:
        return {"bounding_boxes": {"line_metadata": []}, "text": ""}

    # Sort lines by page then vertical position
    raw_lines.sort(key=lambda x: (x["page"], x["base_y"]))

    normalized = []
    collected_text = []

    for idx, line in enumerate(raw_lines):
        bbox = [
            line["page"],
            line["base_y"],
            line["height"],
            line["page_height"],
        ]

        normalized.append({
            "line_index": idx,
            "text": line["text"],
            "bbox": bbox,
            "page": line["page"],
            "page_height": line["page_height"],
        })

        collected_text.append(line["text"])

    return {
        "bounding_boxes": {"line_metadata": normalized},
        "text": "\n".join(collected_text),
    }


# ---------------------------------------------------------
# FIXED HIGHLIGHT CALL (THE IMPORTANT PART)
# ---------------------------------------------------------

async def get_highlight_data(whisper_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch highlight bounding boxes using LLMWhisperer V2."""
    try:
        logger.info("Requesting highlight data via SDK for lines 1-5000")

        result = llmw_client.get_highlight_data(
            whisper_hash=whisper_hash,
            lines="1-5000"   # <-- ONLY THESE TWO ARGUMENTS
        )

        return result

    except Exception as exc:
        logger.error(f"Highlight SDK error: {exc}")
        return None
