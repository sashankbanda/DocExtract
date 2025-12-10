import asyncio
import logging
import os
from typing import Any, Dict

import httpx
from fastapi import HTTPException, UploadFile, status

logger = logging.getLogger(__name__)

LLMWHISPERER_BASE_URL = os.getenv(
    "LLMWHISPERER_BASE_URL",
    "https://llmwhisperer-api.us-central.unstract.com/api/v2",
)
LLMWHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")
POLL_INTERVAL_SECONDS = float(os.getenv("LLMWHISPERER_POLL_INTERVAL", "2.0"))
MAX_POLL_ATTEMPTS = int(os.getenv("LLMWHISPERER_MAX_POLLS", "90"))


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

        # Try to get highlight data from separate endpoint
        highlight_data = await get_highlight_data(
            client=client,
            whisper_hash=whisper_hash,
            headers={"unstract-key": LLMWHISPERER_API_KEY},
        )

    # Try multiple paths to find result_text (API structure varies)
    result_text = _extract_result_text(extraction)
    
    # Extract bounding boxes: prefer highlight_data, fallback to extraction result
    bounding_boxes = None
    if highlight_data:
        bounding_boxes = highlight_data.get("bounding_boxes") or highlight_data.get("line_metadata")
    
    if not bounding_boxes:
        bounding_boxes = _extract_nested(extraction, "line_metadata")
    
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


async def get_highlight_data(
    client: httpx.AsyncClient,
    whisper_hash: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """
    Fetch highlight/bounding box data for a processed document.
    This may be a separate endpoint or included in the extraction result.
    """
    try:
        # Try dedicated highlight endpoint first
        highlight_response = await client.get(
            f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper-highlight",
            params={"whisper_hash": whisper_hash},
            headers=headers,
            timeout=httpx.Timeout(30.0),
        )
        if highlight_response.status_code == 200:
            return highlight_response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Endpoint doesn't exist, will use extraction result instead
            logger.debug("Highlight endpoint not available, using extraction result")
        else:
            logger.warning(f"Highlight endpoint returned error: {exc.response.text}")
    except httpx.HTTPError:
        # Network error, will use extraction result instead
        logger.debug("Failed to reach highlight endpoint, using extraction result")
    
    # Fallback: return empty dict, caller should use extraction result
    return {}
