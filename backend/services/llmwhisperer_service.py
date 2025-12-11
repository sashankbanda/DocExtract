import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from fastapi import HTTPException, UploadFile, status
from unstract.llmwhisperer import LLMWhispererClientV2

from utils.file_saver import get_input_path, save_bytes

logger = logging.getLogger(__name__)

LLMWHISPERER_BASE_URL = os.getenv(
    "LLMWHISPERER_BASE_URL",
    "https://llmwhisperer-api.us-central.unstract.com/api/v2",
)
LLMWHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")
POLL_INTERVAL_SECONDS = float(os.getenv("LLMWHISPERER_POLL_INTERVAL", "2.0"))
MAX_POLL_ATTEMPTS = int(os.getenv("LLMWHISPERER_MAX_POLLS", "90"))

# Initialize LLMWhisperer SDK V2 client
llmw_client = LLMWhispererClientV2(
    base_url="https://llmwhisperer-api.us-central.unstract.com/api/v2",
    api_key=LLMWHISPERER_API_KEY
)


async def process_upload_file(upload_file: UploadFile) -> Dict[str, Any]:
    """Upload a file to LLMWhisperer v2 and poll until the extraction completes."""
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

    # Save original file to input_files/ as 01_<filename> (raw file, no extension change)
    # This preserves the original uploaded file for reference
    try:
        input_path = get_input_path(upload_file.filename or "unknown", prefix="01")
        # Add original extension if it exists
        if upload_file.filename:
            original_ext = Path(upload_file.filename).suffix
            if original_ext:
                input_path = input_path.with_suffix(original_ext)
        save_bytes(input_path, file_bytes)
        logger.info("Saved input file to %s", input_path)
    except Exception as e:
        logger.warning(f"Failed to save input file: {e}")
        # Continue processing even if saving fails

    headers = {
        "unstract-key": LLMWHISPERER_API_KEY,
        "Content-Type": "application/octet-stream",
    }

    params = {
        "mode": "form",
        "output_mode": "layout_preserving",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        try:
            response = await client.post(
                f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper",
                params=params,
                content=file_bytes,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"LLMWhisperer upload failed: {exc.response.text}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reach LLMWhisperer: {exc}",
            ) from exc

        payload = response.json()
        logger.info(f"LLMWhisperer initial response: {payload}")
        whisper_hash = _extract_whisper_hash(payload)

        extraction = await _poll_until_complete(
            client=client,
            whisper_hash=whisper_hash,
            headers={"unstract-key": LLMWHISPERER_API_KEY},
        )

    # Try multiple paths to find result_text (API structure varies)
    result_text = _extract_result_text(extraction)
    
    # Get highlight data using SDK
    highlight_result = await get_highlight_data(whisper_hash)

    if highlight_result and "line_metadata" in highlight_result:
        line_metadata = highlight_result["line_metadata"]
    else:
        logger.warning("No highlight metadata from SDK, using fallback generation.")
        line_metadata = []
    
    # Normalize bounding_boxes structure and generate words
    if line_metadata and result_text:
        words = _generate_word_level_boxes_from_line_metadata(line_metadata, result_text)
    else:
        words = []

    bounding_boxes = {
        "line_metadata": line_metadata,
        "words": words,
    }
    logger.info(f"Generated {len(words)} word boxes from {len(line_metadata)} lines for {upload_file.filename or 'unknown'}")
    
    return {
        "file_name": upload_file.filename or "unknown",
        "result_text": result_text,
        "whisper_hash": whisper_hash,
        "bounding_boxes": bounding_boxes,
        "pages": _extract_nested(extraction, "pages"),
    }


def _extract_result_text(data: Dict[str, Any]) -> str:
    """Try multiple paths to extract result_text from the response."""
    # Direct path
    if data.get("result_text"):
        return data["result_text"]
    
    # Nested under extraction
    extraction = data.get("extraction", {})
    if isinstance(extraction, dict) and extraction.get("result_text"):
        return extraction["result_text"]
    
    # Nested under extraction.extraction (double nested)
    inner = extraction.get("extraction", {})
    if isinstance(inner, dict) and inner.get("result_text"):
        return inner["result_text"]
    
    # Try "text" key as fallback
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


async def _poll_until_complete(
    client: httpx.AsyncClient,
    whisper_hash: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    for _ in range(MAX_POLL_ATTEMPTS):
        try:
            status_response = await client.get(
                f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper-status",
                params={"whisper_hash": whisper_hash},
                headers=headers,
            )
            status_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"LLMWhisperer status check failed: {exc.response.text}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to poll LLMWhisperer status: {exc}",
            ) from exc

        status_payload = status_response.json()
        status_value = (status_payload.get("status") or "").lower()

        if status_value in {"processed", "completed", "done"}:
            return await _retrieve_result(client, whisper_hash, headers)

        if status_value in {"failed", "error"}:
            message = status_payload.get("message") or "Unknown error"
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLMWhisperer extraction failed for {whisper_hash}: {message}",
            )

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail="Timed out waiting for LLMWhisperer to finish processing.",
    )


async def _retrieve_result(
    client: httpx.AsyncClient,
    whisper_hash: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    try:
        retrieve_response = await client.get(
            f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper-retrieve",
            params={"whisper_hash": whisper_hash},
            headers=headers,
        )
        retrieve_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"LLMWhisperer retrieve failed: {exc.response.text}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve LLMWhisperer result: {exc}",
        ) from exc

    result = retrieve_response.json()
    logger.info(f"LLMWhisperer retrieve response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
    return result




def _generate_word_level_boxes_from_line_metadata(
    line_metadata: List[Dict[str, Any]], text: str
) -> List[Dict[str, Any]]:
    """
    Create word-level bounding boxes using raw_box + text splitting.
    Uses per-character width based on raw_box width.
    """
    import re

    words: List[Dict[str, Any]] = []
    global_word_index = 0

    for line in line_metadata:
        if not isinstance(line, dict):
            continue

        raw_box = line.get("raw_box") or None
        if not raw_box or not isinstance(raw_box, list) or len(raw_box) < 4:
            continue

        # raw_box expected: [page, x_or_base_y, width_or_height, page_height]
        page = raw_box[0]
        raw_y = raw_box[1]
        raw_height = raw_box[2]
        raw_page_height = raw_box[3]

        line_text = line.get("text", "")
        if not isinstance(line_text, str) or not line_text:
            continue

        # Strip hex prefixes like "0x07: "
        line_text = re.sub(r"^0x[0-9A-Fa-f]+:\\s*", "", line_text).strip()
        if not line_text:
            continue

        tokens = line_text.split()
        if not tokens:
            continue

        total_chars = sum(len(t) for t in tokens)
        if total_chars == 0:
            continue

        # Estimate line width; raw_box does not provide width explicitly.
        # Use page_height as a proxy (A4 aspect ratio) else fall back to raw_height.
        if raw_page_height:
            line_width = float(raw_page_height) * 0.707
        else:
            line_width = float(raw_height)

        width_per_char = line_width / total_chars if total_chars else 0
        x_cursor = 0.0
        y = float(raw_y)
        height = float(raw_height) if raw_height else 0.0

        for token in tokens:
            token_width = width_per_char * len(token)
            words.append(
                {
                    "index": global_word_index,
                    "text": token,
                    "page": int(page) if page is not None else 1,
                    "bbox": {
                        "x": x_cursor,
                        "y": y,
                        "width": token_width,
                        "height": height,
                    },
                    "page_height": float(raw_page_height) if raw_page_height else 0,
                }
            )
            x_cursor += token_width
            global_word_index += 1

    logger.info(f"Generated {len(words)} word boxes from {len(line_metadata)} lines.")
    return words


async def get_highlight_data(whisper_hash: str) -> Optional[Dict[str, Any]]:
    """
    Fetch highlight bounding boxes using LLMWhisperer SDK V2.
    Uses full line range and normalizes raw_box.
    """
    try:
        line_range = "0x01-0xFFFF"
        logger.info(f"Requesting highlight data via SDK for range {line_range}")

        data = llmw_client.get_highlight_data(
            whisper_hash=whisper_hash,
            lines=line_range,
        )

        if not data:
            logger.warning("Highlight data empty — fallback will be used.")
            return None

        import re

        line_metadata: List[Dict[str, Any]] = []

        for line_no, entry in data.items():
            if not isinstance(entry, dict):
                continue

            raw_box = entry.get("raw") or entry.get("raw_box") or None
            if not raw_box or not isinstance(raw_box, list) or len(raw_box) < 4:
                # Missing raw_box is not valid
                logger.warning(f"Missing raw_box for line {line_no}, skipping.")
                continue

            page = entry.get("page", raw_box[0])
            base_y = entry.get("base_y", raw_box[1])
            height = entry.get("height", raw_box[2])
            page_height = entry.get("page_height", raw_box[3])

            line_text = entry.get("text", "")
            if isinstance(line_text, str):
                line_text = re.sub(r"^0x[0-9A-Fa-f]+:\\s*", "", line_text)
            else:
                line_text = ""

            line_metadata.append(
                {
                    "line_no": line_no,
                    "raw_box": [page, base_y, height, page_height],
                    "text": line_text,
                }
            )

        logger.info(f"Received {len(line_metadata)} highlight lines from SDK.")
        return {"line_metadata": line_metadata}

    except Exception as e:
        logger.error(f"Highlight SDK error: {e}")
        return None
