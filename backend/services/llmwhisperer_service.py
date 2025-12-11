import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import HTTPException, UploadFile, status

from utils.file_saver import get_input_path, save_bytes

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
    
    # Parse hex line numbers from layout_preserving text (e.g., "0x01:", "0x0A:")
    # These are used to request exact line ranges from get_highlight_data
    line_numbers = _parse_hex_line_numbers(result_text)
    
    # Get highlight data with exact line ranges (not "1-5000")
    highlight_data = await get_highlight_data(
        client=client,
        whisper_hash=whisper_hash,
        line_numbers=line_numbers,
        headers={"unstract-key": LLMWHISPERER_API_KEY},
    )
    
    # Extract bounding boxes: prefer highlight_data, fallback to extraction result
    bounding_boxes = None
    if highlight_data:
        bounding_boxes = highlight_data.get("bounding_boxes") or highlight_data.get("line_metadata")
    
    if not bounding_boxes:
        bounding_boxes = _extract_nested(extraction, "line_metadata")
    
    # Generate word-level boxes from line-level boxes
    # LLMWhisperer returns line-level boxes, we need word-level for precise highlighting
    if bounding_boxes and result_text:
        bounding_boxes = _generate_word_level_boxes(bounding_boxes, result_text)
    
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


def _parse_hex_line_numbers(text: str) -> List[int]:
    """
    Parse hex line numbers from layout_preserving text.
    
    LLMWhisperer adds line numbers in hex format like "0x01:", "0x0A:", etc.
    We extract these to request exact line ranges from get_highlight_data.
    
    Args:
        text: Layout-preserving text with hex line numbers
        
    Returns:
        List of line numbers (as integers, 1-based)
    """
    import re
    line_numbers = set()
    
    # Pattern to match hex line numbers: "0x01:", "0x0A:", etc.
    pattern = r'0x([0-9A-Fa-f]+):'
    matches = re.findall(pattern, text)
    
    for match in matches:
        try:
            line_num = int(match, 16)  # Convert hex to int
            line_numbers.add(line_num)
        except ValueError:
            continue
    
    return sorted(list(line_numbers))


def _generate_word_level_boxes(
    bounding_boxes: Dict[str, Any], text: str
) -> Dict[str, Any]:
    """
    Generate word-level bounding boxes from line-level boxes.
    
    LLMWhisperer returns line-level boxes. We split each line into words
    and proportionally segment the bounding box based on text widths.
    
    Args:
        bounding_boxes: Line-level bounding box data from LLMWhisperer
        text: The layout-preserving text
        
    Returns:
        Dictionary with word-level boxes: {word_index: {page, x, y, width, height}}
    """
    word_boxes: Dict[str, Dict[str, float]] = {}
    
    # Extract line metadata
    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    if not isinstance(line_metadata, list):
        logger.warning("No line_metadata found, cannot generate word-level boxes")
        return bounding_boxes
    
    # Split text into words (preserving order for word index)
    # Remove hex line numbers from text for word indexing
    import re
    text_clean = re.sub(r'0x[0-9A-Fa-f]+:\s*', '', text)
    all_words = text_clean.split()
    word_index = 0
    
    # Process each line
    for line_data in line_metadata:
        if not isinstance(line_data, dict):
            continue
        
        # Get line text and bounding box
        line_text = line_data.get("text", "")
        line_no = line_data.get("line_no") or line_data.get("line_number") or line_data.get("line")
        
        # Extract bounding box
        bbox = line_data.get("bbox") or line_data.get("bounding_box") or line_data.get("box") or line_data.get("raw_box")
        if not bbox:
            continue
        
        # Parse bounding box format
        page = 1
        line_x = 0
        line_y = 0
        line_width = 0
        line_height = 0
        
        if isinstance(bbox, list) and len(bbox) >= 4:
            # Format: [page, base_y, height, page_height]
            page = int(bbox[0]) if bbox[0] else 1
            line_y = float(bbox[1]) if bbox[1] else 0
            line_height = float(bbox[2]) if bbox[2] else 0
            page_height = float(bbox[3]) if len(bbox) > 3 and bbox[3] else 0
            # Estimate width based on page height (assuming standard page aspect ratio)
            # For A4: width/height ≈ 0.707, so width ≈ height * 0.707
            # Use page_height if available, otherwise estimate from line_height
            if page_height > 0:
                line_width = page_height * 0.707  # A4 aspect ratio
            else:
                line_width = line_height * 50  # Rough estimate
            # Try to get actual width from line_data if available
            if "width" in line_data:
                line_width = float(line_data["width"])
            elif "x" in line_data and "right" in line_data:
                line_width = float(line_data["right"]) - float(line_data["x"])
            elif "left" in line_data and "right" in line_data:
                line_width = float(line_data["right"]) - float(line_data["left"])
        elif isinstance(bbox, dict):
            page = int(bbox.get("page", 1))
            line_x = float(bbox.get("x", bbox.get("left", 0)))
            line_y = float(bbox.get("y", bbox.get("top", bbox.get("base_y", 0))))
            line_width = float(bbox.get("width", bbox.get("right", 0) - bbox.get("left", 0)))
            line_height = float(bbox.get("height", bbox.get("bottom", 0) - bbox.get("top", 0)))
        
        if line_width <= 0 or line_height <= 0:
            continue
        
        # Split line into words
        line_words = line_text.split()
        if not line_words:
            continue
        
        # Calculate proportional widths for each word
        # Estimate width based on character count (rough approximation)
        total_chars = sum(len(word) for word in line_words)
        if total_chars == 0:
            continue
        
        current_x = line_x
        for word in line_words:
            # Proportional width based on character count
            word_width_ratio = len(word) / total_chars
            word_width = line_width * word_width_ratio
            
            # Store word-level box
            word_boxes[str(word_index)] = {
                "page": float(page),
                "x": current_x,
                "y": line_y,
                "width": word_width,
                "height": line_height,
            }
            
            current_x += word_width
            word_index += 1
    
    # Return word-level boxes in the expected format
    return {
        "words": [
            {
                "index": int(idx),
                "page": int(box["page"]),
                "bbox": {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                }
            }
            for idx, box in word_boxes.items()
        ],
        "line_metadata": line_metadata,  # Keep original for reference
    }


async def get_highlight_data(
    client: httpx.AsyncClient,
    whisper_hash: str,
    line_numbers: List[int],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """
    Fetch highlight/bounding box data for a processed document.
    
    Uses exact line number ranges parsed from layout_preserving text,
    not a generic "1-5000" range.
    
    Args:
        client: HTTP client
        whisper_hash: Whisper hash for the document
        line_numbers: List of line numbers to request (1-based, from hex parsing)
        headers: Request headers
        
    Returns:
        Highlight data with bounding boxes
    """
    if not line_numbers:
        logger.warning("No line numbers provided, requesting all lines")
        line_numbers = [1]  # Fallback
    
    try:
        # Build line range string from parsed line numbers
        # Format: "1,2,3" or "1-10" if consecutive
        if len(line_numbers) == 1:
            line_range = str(line_numbers[0])
        else:
            # Group consecutive numbers
            ranges = []
            start = line_numbers[0]
            end = line_numbers[0]
            
            for i in range(1, len(line_numbers)):
                if line_numbers[i] == end + 1:
                    end = line_numbers[i]
                else:
                    if start == end:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{end}")
                    start = line_numbers[i]
                    end = line_numbers[i]
            
            # Add last range
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            
            line_range = ",".join(ranges)
        
        # Try dedicated highlight endpoint with exact line ranges
        highlight_response = await client.get(
            f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper-highlight",
            params={
                "whisper_hash": whisper_hash,
                "line_range": line_range,
            },
            headers=headers,
            timeout=httpx.Timeout(30.0),
        )
        if highlight_response.status_code == 200:
            data = highlight_response.json()
            # Ensure raw_box is never null
            if isinstance(data, dict) and "line_metadata" in data:
                for line in data.get("line_metadata", []):
                    if isinstance(line, dict) and not line.get("raw_box") and line.get("bbox"):
                        line["raw_box"] = line["bbox"]
            return data
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
