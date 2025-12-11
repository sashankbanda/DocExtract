import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

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
    
    # Get highlight data with fixed catch-all range
    highlight_response = await get_highlight_data(whisper_hash=whisper_hash)
    
    # Standardize bounding_boxes structure
    # Only use fallback if highlight API returns empty dict or no line_metadata
    if not highlight_response or not isinstance(highlight_response, dict):
        # Empty response - use fallback
        logger.warning("Highlight API returned empty response, using fallback generation from extraction result")
        line_metadata = _extract_nested(extraction, "line_metadata")
        if line_metadata:
            bounding_boxes = {"line_metadata": line_metadata}
        else:
            bounding_boxes = None
    elif not highlight_response.get("line_metadata"):
        # No line_metadata in response - use fallback
        logger.warning("Highlight API returned no line_metadata, using fallback generation from extraction result")
        line_metadata = _extract_nested(extraction, "line_metadata")
        if line_metadata:
            bounding_boxes = {"line_metadata": line_metadata}
        else:
            bounding_boxes = None
    else:
        # Valid response with line_metadata - use it directly
        bounding_boxes = highlight_response
        # Ensure it's a dict with line_metadata key
        if isinstance(bounding_boxes, list):
            bounding_boxes = {"line_metadata": bounding_boxes}
        logger.info(f"Using {len(bounding_boxes.get('line_metadata', []))} lines from highlight API")
    
    # Generate word-level boxes from line-level boxes
    # Only generate if we have valid bounding_boxes and text
    if bounding_boxes and result_text:
        n_lines_before = len(bounding_boxes.get("line_metadata", [])) if isinstance(bounding_boxes, dict) else 0
        bounding_boxes = _generate_word_level_boxes(bounding_boxes, result_text)
        n_words_after = len(bounding_boxes.get("words", [])) if isinstance(bounding_boxes, dict) else 0
        logger.info(f"Generated {n_words_after} word boxes from {n_lines_before} lines for {upload_file.filename or 'unknown'}")
    
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




def _generate_word_level_boxes(
    bounding_boxes: Dict[str, Any], text: str
) -> Dict[str, Any]:
    """
    Generate word-level bounding boxes from line-level boxes.
    
    Handles cases where raw_box is null by generating boxes from line_metadata.
    Uses proportional width calculation based on character count.
    
    Args:
        bounding_boxes: Line-level bounding box data (must have line_metadata)
        text: The layout-preserving text with hex line numbers
        
    Returns:
        Dictionary with word-level boxes and updated line_metadata:
        {
            "words": [{index, page, text, bbox: {x, y, width, height}}],
            "line_metadata": [...]  # with raw_box populated
        }
    """
    import re
    
    # Extract line metadata
    line_metadata = bounding_boxes.get("line_metadata") or bounding_boxes.get("lines")
    if not isinstance(line_metadata, list):
        logger.warning("No line_metadata found, cannot generate word-level boxes")
        return bounding_boxes
    
    words_output: List[Dict[str, Any]] = []
    global_word_index = 0
    updated_line_metadata: List[Dict[str, Any]] = []
    
    # Process each line
    for line_data in line_metadata:
        if not isinstance(line_data, dict):
            updated_line_metadata.append(line_data)
            continue
        
        # Get line text - remove hex line numbers for word extraction
        line_text_raw = line_data.get("text", "")
        line_text = re.sub(r'0x[0-9A-Fa-f]+:\s*', '', line_text_raw).strip()
        
        # Skip empty lines
        if not line_text:
            updated_line_metadata.append(line_data)
            continue
        
        # Extract bounding box - API returns "raw" field, normalize to "raw_box"
        # Use: raw_box = line["raw"] or line["raw_box"]
        raw_box = line_data.get("raw") or line_data.get("raw_box")
        bbox = raw_box or line_data.get("bbox") or line_data.get("bounding_box") or line_data.get("box")
        
        # Parse bounding box format
        page = 1
        line_x = 0
        line_y = 0
        line_width = 0
        line_height = 0
        page_height = 0
        page_width = 0
        
        if bbox:
            if isinstance(bbox, list) and len(bbox) >= 4:
                # Format: [page, base_y, height, page_height]
                page = int(bbox[0]) if bbox[0] else 1
                line_y = float(bbox[1]) if bbox[1] else 0
                line_height = float(bbox[2]) if bbox[2] else 0
                page_height = float(bbox[3]) if len(bbox) > 3 and bbox[3] else 0
                # Estimate width from page height (A4 aspect ratio ≈ 0.707)
                if page_height > 0:
                    page_width = page_height * 0.707
                    line_width = page_width  # Full line width
                else:
                    line_width = line_height * 50  # Rough estimate
            elif isinstance(bbox, dict):
                page = int(bbox.get("page", 1))
                line_x = float(bbox.get("x", bbox.get("left", 0)))
                line_y = float(bbox.get("y", bbox.get("top", bbox.get("base_y", 0))))
                line_width = float(bbox.get("width", bbox.get("right", 0) - bbox.get("left", 0)))
                line_height = float(bbox.get("height", bbox.get("bottom", 0) - bbox.get("top", 0)))
                page_height = float(bbox.get("page_height", bbox.get("pageHeight", 0)))
                page_width = float(bbox.get("page_width", bbox.get("pageWidth", 0)))
        
        # If no bbox found, try to infer from line_data fields
        if line_width <= 0 or line_height <= 0:
            # Try to get from line_data directly
            if "width" in line_data:
                line_width = float(line_data["width"])
            elif "x" in line_data and "right" in line_data:
                line_x = float(line_data.get("x", 0))
                line_width = float(line_data["right"]) - line_x
            elif "left" in line_data and "right" in line_data:
                line_x = float(line_data.get("left", 0))
                line_width = float(line_data["right"]) - line_x
            
            if "height" in line_data:
                line_height = float(line_data["height"])
            elif "y" in line_data or "base_y" in line_data:
                line_y = float(line_data.get("y", line_data.get("base_y", 0)))
            
            page = int(line_data.get("page", line_data.get("page_number", 1)))
        
        # If still no valid dimensions, try to use raw_box directly
        if line_width <= 0 or line_height <= 0:
            if raw_box and isinstance(raw_box, list) and len(raw_box) >= 4:
                # Use raw_box directly: [page, y, height, page_height]
                page = int(raw_box[0]) if raw_box[0] else 1
                line_y = float(raw_box[1]) if raw_box[1] else 0
                line_height = float(raw_box[2]) if raw_box[2] else 0
                page_height = float(raw_box[3]) if raw_box[3] else 0
                # Estimate width from page height
                if page_height > 0:
                    page_width = page_height * 0.707  # A4 aspect ratio
                    line_width = page_width
                else:
                    line_width = line_height * 50  # Rough estimate
            else:
                # No valid dimensions and no raw_box - skip this line
                if not raw_box:
                    updated_line = {**line_data, "raw_box": None}
                else:
                    updated_line = {**line_data, "raw_box": raw_box}
                updated_line_metadata.append(updated_line)
                continue
        
        # Split line into words (preserve punctuation attached to tokens)
        line_words = line_text.split()
        if not line_words:
            # No words, but ensure raw_box is set
            if not raw_box:
                updated_line = {**line_data, "raw_box": [page, line_y, line_height, page_height] if page_height > 0 else [page, line_y, line_height, 0]}
            else:
                updated_line = line_data
            updated_line_metadata.append(updated_line)
            continue
        
        # Calculate proportional widths for each word
        total_chars = sum(len(word) for word in line_words)
        if total_chars == 0:
            total_chars = len(line_words)  # Fallback: equal width
        
        current_x = line_x
        for word in line_words:
            # Proportional width based on character count
            word_width_ratio = len(word) / total_chars if total_chars > 0 else 1.0 / len(line_words)
            word_width = round(line_width * word_width_ratio)
            
            # Ensure minimum width
            if word_width < 1:
                word_width = 1
            
            # Store word-level box with text
            words_output.append({
                "index": global_word_index,
                "page": page,
                "text": word,
                "bbox": {
                    "x": current_x,
                    "y": line_y,
                    "width": word_width,
                    "height": line_height,
                }
            })
            
            current_x += word_width
            global_word_index += 1
        
        # Ensure raw_box is populated for the line
        # Normalize: ensure every line has raw_box with [page, y, height, page_height]
        if not raw_box:
            # Generate from computed values
            raw_box = [page, line_y, line_height, page_height] if page_height > 0 else [page, line_y, line_height, 0]
            logger.debug(f"Generated raw_box for line {line_data.get('line_number', 'unknown')}: {raw_box}")
        elif isinstance(raw_box, list) and len(raw_box) >= 4:
            # Ensure page and page_height are set in line_data
            if "page" not in line_data:
                line_data["page"] = int(raw_box[0]) if raw_box[0] else 1
            if "page_height" not in line_data:
                line_data["page_height"] = float(raw_box[3]) if len(raw_box) > 3 and raw_box[3] else 0
        
        updated_line = {**line_data, "raw_box": raw_box}
        # Ensure page and page_height are in the updated line
        if "page" not in updated_line:
            updated_line["page"] = page
        if "page_height" not in updated_line and page_height > 0:
            updated_line["page_height"] = page_height
        updated_line_metadata.append(updated_line)
    
    # Log generation results
    logger.info(f"Generated {len(words_output)} word boxes from {len(line_metadata)} lines")
    
    # Return both word-level boxes and updated line_metadata
    result = {
        "words": words_output,
        "line_metadata": updated_line_metadata,
    }
    
    # Preserve other keys from original bounding_boxes
    for key in bounding_boxes:
        if key not in {"words", "line_metadata", "lines"}:
            result[key] = bounding_boxes[key]
    
    return result


async def get_highlight_data(
    whisper_hash: str,
) -> Dict[str, Any]:
    """
    Fetch highlight/bounding box data for a processed document.
    
    Uses fixed catch-all range "0x01-0xFFFF" to ensure API returns
    bounding boxes for every line.
    
    Args:
        whisper_hash: Whisper hash for the document
        
    Returns:
        Highlight data with bounding boxes, or empty dict if API fails
    """
    import httpx
    
    if not LLMWHISPERER_API_KEY:
        logger.warning("LLMWHISPERER_API_KEY not configured, cannot fetch highlight data")
        return {}
    
    headers = {
        "unstract-key": LLMWHISPERER_API_KEY,
    }
    
    # Use fixed catch-all range to get all lines
    line_range = "0x01-0xFFFF"
    logger.info(f"Using full highlight range: {line_range}")
    
    try:
        # Create own client to avoid closed client issues
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Call highlight endpoint with fixed range
            highlight_response = await client.get(
                f"{LLMWHISPERER_BASE_URL.rstrip('/')}/whisper-highlight",
                params={
                    "whisper_hash": whisper_hash,
                    "line_range": line_range,
                },
                headers=headers,
            )
            highlight_response.raise_for_status()
            data = highlight_response.json()
            
            # Normalize raw_box from "raw" field
            if isinstance(data, dict) and "line_metadata" in data:
                line_count = 0
                for line in data.get("line_metadata", []):
                    if isinstance(line, dict):
                        line_count += 1
                        # API returns "raw" field, normalize to "raw_box"
                        raw_box = line.get("raw") or line.get("raw_box")
                        if raw_box:
                            line["raw_box"] = raw_box
                            # Ensure page and page_height are set
                            if "page" not in line and isinstance(raw_box, list) and len(raw_box) > 0:
                                line["page"] = int(raw_box[0]) if raw_box[0] else 1
                            if "page_height" not in line and isinstance(raw_box, list) and len(raw_box) > 3:
                                line["page_height"] = float(raw_box[3]) if raw_box[3] else 0
                
                logger.info(f"Highlight API returned {line_count} lines")
                return data
            
            # If no line_metadata, return empty dict
            logger.warning("Highlight API returned no line_metadata")
            return {}
            
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.warning("Highlight endpoint not available (404)")
        else:
            logger.warning(f"Highlight endpoint returned error: {exc.response.status_code} - {exc.response.text}")
        return {}
    except httpx.HTTPError as exc:
        logger.warning(f"Failed to reach highlight endpoint: {exc}")
        return {}
