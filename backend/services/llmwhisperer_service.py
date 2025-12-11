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
        "add_line_nos": "true",
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
        line_metadata = _extract_nested(extraction, "line_metadata") or []
    
    # Normalize bounding_boxes structure
    # Generate word-level boxes from line-level boxes
    if line_metadata and result_text:
        words = _generate_word_level_boxes_from_line_metadata(line_metadata, result_text)
        bounding_boxes = {
            "line_metadata": line_metadata,
            "words": words
        }
        logger.info(f"Generated {len(words)} word boxes from {len(line_metadata)} lines for {upload_file.filename or 'unknown'}")
    else:
        bounding_boxes = {
            "line_metadata": line_metadata,
            "words": []
        }
    
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
    Create word-level bounding boxes using real raw_box from highlight API.
    
    Args:
        line_metadata: List of line metadata dicts with raw_box
        text: The layout-preserving text (for reference, not used directly)
        
    Returns:
        List of word boxes with index, page, text, bbox coordinates
    """
    words = []
    global_word_index = 0
    
    for line in line_metadata:
        if not isinstance(line, dict):
            continue
            
        raw_box = line.get("raw_box")
        if not raw_box or not isinstance(raw_box, list) or len(raw_box) < 4:
            continue
        
        page, base_y, height, page_height = raw_box[0], raw_box[1], raw_box[2], raw_box[3]
        
        line_text = line.get("text", "")
        if not line_text:
            continue
        
        # Remove hex line numbers for word extraction
        import re
        line_text = re.sub(r'0x[0-9A-Fa-f]+:\s*', '', line_text).strip()
        
        tokens = line_text.split()
        if not tokens:
            continue
        
        # Compute per-word width
        total_chars = sum(len(t) for t in tokens)
        if total_chars == 0:
            continue
        
        # Estimate line width from page height (A4 aspect ratio)
        if page_height > 0:
            line_width = page_height * 0.707  # A4 aspect ratio
        else:
            line_width = height * 50  # Rough estimate
        
        x_cursor = 0
        for token in tokens:
            token_width_ratio = len(token) / total_chars
            token_width = line_width * token_width_ratio
            
            words.append({
                "index": global_word_index,
                "text": token,
                "page": int(page),
                "bbox": {
                    "x": x_cursor,
                    "y": float(base_y),
                    "width": token_width,
                    "height": float(height),
                },
                "page_height": float(page_height) if page_height else 0
            })
            
            x_cursor += token_width
            global_word_index += 1
    
    logger.info(f"Generated {len(words)} word boxes from {len(line_metadata)} lines.")
    return words


async def get_highlight_data(whisper_hash: str) -> Optional[Dict[str, Any]]:
    """
    Fetch highlight bounding boxes using LLMWhisperer SDK V2.
    
    This completely replaces the old httpx-based highlight logic.
    
    Args:
        whisper_hash: Whisper hash for the document
        
    Returns:
        Dict with line_metadata, or None if API fails
    """
    try:
        # Always fetch a large range
        line_range = "1-5000"
        logger.info(f"Requesting highlight data via SDK for range {line_range}")
        
        data = llmw_client.get_highlight_data(
            whisper_hash=whisper_hash,
            lines=line_range
        )
        
        if not data:
            logger.warning("Highlight data empty — fallback will be used.")
            return None
        
        line_metadata = []
        
        for line_no, entry in data.items():
            raw = entry.get("raw") or entry.get("raw_box")
            
            if not raw or len(raw) < 4:
                logger.warning(f"Missing raw for line {line_no}, skipping.")
                continue
            
            # raw = [page, base_y, height, page_height]
            page = entry.get("page", raw[0])
            base_y = entry.get("base_y", raw[1])
            height = entry.get("height", raw[2])
            page_height = entry.get("page_height", raw[3])
            
            line_metadata.append({
                "line_no": line_no,
                "raw_box": [page, base_y, height, page_height],
                "text": entry.get("text", "")
            })
        
        logger.info(f"Received {len(line_metadata)} highlight lines from SDK.")
        return {"line_metadata": line_metadata}
        
    except Exception as e:
        logger.error(f"Highlight SDK error: {e}")
        return None
