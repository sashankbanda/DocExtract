import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
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
        logger.exception("LLMWhisperer whisper failed")
        raise HTTPException(502, f"LLMWhisperer whisper failed: {exc}")

    original_text = _extract_result_text(whisper_result)
    whisper_hash = _extract_whisper_hash(whisper_result)
    logger.info(f"Extracted whisper_hash: {whisper_hash}")

    # ---- 2. Fetch highlights (real bounding boxes) ----
    highlight_data = await get_highlight_data(whisper_hash)
    if highlight_data:
        first_key = next(iter(highlight_data), None)
        if first_key:
            logger.info(f"Highlight sample: {highlight_data[first_key]}")
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


# ---------------------
# Result parsers
# ---------------------
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


def _extract_nested(data: Dict[str, Any], key: str):
    if key in data:
        return data[key]
    extraction = data.get("extraction", {})
    if key in extraction:
        return extraction[key]
    inner = extraction.get("extraction", {}) if isinstance(extraction, dict) else {}
    if key in inner:
        return inner[key]
    return None


def _extract_whisper_hash(payload: Dict[str, Any]) -> str:
    # robustly check multiple places for whisper hash
    extraction = payload.get("extraction", {}) or {}
    for k in ("whisper_hash", "whisper_hash_id", "hash", "whisper_id", "job_id", "document_hash"):
        if payload.get(k):
            return str(payload[k])
        if extraction.get(k):
            return str(extraction[k])
    inner = extraction.get("extraction", {}) if isinstance(extraction, dict) else {}
    for k in ("whisper_hash", "hash", "job_id"):
        if inner.get(k):
            return str(inner[k])
    raise HTTPException(502, "LLMWhisperer response missing whisper_hash.")


# ---------------------
# Line normalization
# ---------------------
def _normalize_line_metadata(highlight_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert SDK highlight structure into:
      {
        "bounding_boxes": {
            "line_metadata": [
                { "line_index": int, "text": str, "page": int, "page_height": int,
                  "raw_box": [page, base_y, height, page_height], "bbox": [page, base_y, height, page_height] }
                ...
            ]
        },
        "text": "joined lines"
      }
    Handles page==0 by coercing to page 1.
    """
    if not highlight_result:
        return {"bounding_boxes": {"line_metadata": []}, "text": ""}

    raw_lines: List[Dict[str, Any]] = []

    # handle two shapes:
    # A) dict keyed by "1","2"... -> each value is an object
    # B) list of line objects
    if isinstance(highlight_result, dict):
        iterator = highlight_result.items()
    elif isinstance(highlight_result, list):
        iterator = ((str(i + 1), v) for i, v in enumerate(highlight_result))
    else:
        logger.warning("Unexpected highlight_result type: %s", type(highlight_result))
        return {"bounding_boxes": {"line_metadata": []}, "text": ""}

    for key, entry in iterator:
        if not isinstance(entry, dict):
            continue

        # text may be present under different keys
        text = (entry.get("text") or entry.get("line_text") or entry.get("value") or "").strip()
        # Some LLMWhisperer outputs don't include the text in highlight payload; skip those
        if not text:
            continue

        # find the raw box - multiple naming possibilities
        raw_box = None
        for candidate in ("raw", "raw_box", "bbox", "box"):
            if candidate in entry and entry[candidate]:
                raw_box = entry[candidate]
                break

        # fallback: find first list-like value of length >= 4
        if raw_box is None:
            for v in entry.values():
                if isinstance(v, list) and len(v) >= 4:
                    raw_box = v
                    break

        if not raw_box or not isinstance(raw_box, list) or len(raw_box) < 4:
            # no usable box for this line
            continue

        # map values: [page, base_y, height, page_height]
        page_raw, base_y_raw, height_raw, page_height_raw = raw_box[:4]

        try:
            page = int(float(page_raw))
        except Exception:
            page = 1

        # coerce page 0 -> 1 (common in LLMWhisperer)
        if page == 0:
            page = 1

        try:
            base_y = int(float(base_y_raw))
        except Exception:
            base_y = 0
        try:
            height = int(float(height_raw))
        except Exception:
            height = 0
        try:
            page_height = int(float(page_height_raw))
        except Exception:
            page_height = 0

        # ignore placeholder boxes that are all zeros
        if page == 0 and base_y == 0 and height == 0 and page_height == 0:
            continue

        raw_lines.append(
            {
                "text": text,
                "page": page,
                "base_y": base_y,
                "height": height,
                "page_height": page_height,
                "raw_box": [page, base_y, height, page_height],
            }
        )

    if not raw_lines:
        return {"bounding_boxes": {"line_metadata": []}, "text": ""}

    raw_lines.sort(key=lambda x: (x["page"], x["base_y"]))

    normalized: List[Dict[str, Any]] = []
    collected_text: List[str] = []

    for idx, line in enumerate(raw_lines):
        bbox = line["raw_box"]
        entry = {
            "line_index": idx + 1,  # 1-based index to match some consumers
            "text": line["text"],
            "page": line["page"],
            "page_height": line["page_height"],
            "raw_box": bbox,
            "bbox": bbox,
        }
        normalized.append(entry)
        collected_text.append(line["text"])

    return {
        "bounding_boxes": {"line_metadata": normalized},
        "text": "\n".join(collected_text),
    }


# ---------------------
# Highlight fetch
# ---------------------
async def get_highlight_data(whisper_hash: str) -> Optional[Dict[str, Any]]:
    """Fetch highlight bounding boxes using LLMWhisperer V2.

    Only pass the supported arguments to the SDK call. Return None on error.
    """
    try:
        logger.info("Requesting highlight data via SDK for lines 1-5000")

        result = llmw_client.get_highlight_data(
            whisper_hash=whisper_hash,
            lines="1-5000",
        )

        # result may be dict keyed by string line numbers
        if isinstance(result, dict):
            return result

        # If SDK returned a list, convert to dict keyed by 1..n
        if isinstance(result, list):
            out = {}
            for i, item in enumerate(result, start=1):
                out[str(i)] = item
            return out

        return None

    except Exception as exc:
        logger.exception("Highlight SDK error")
        return None
