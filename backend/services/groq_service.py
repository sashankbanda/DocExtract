import json
import logging
import os
from typing import Any, Dict

import httpx
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

GROQ_API_BASE_URL = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


class GroqService:
    """Service for interacting with Groq API for LLM-based field extraction."""

    def __init__(self):
        """Initialize GroqService with API key and model configuration."""
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not configured.")
        self.api_key = GROQ_API_KEY
        self.api_base_url = GROQ_API_BASE_URL.rstrip("/")
        self.model = GROQ_MODEL

    async def extract(self, prompt: str) -> str:
        """
        Send a prompt to Groq API and return the raw text response.

        Args:
            prompt: The prompt text to send to the LLM

        Returns:
            Raw text response from the LLM

        Raises:
            HTTPException: If the API request fails
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise information extraction assistant. "
                        "Extract the requested fields and return ONLY valid JSON. "
                        "No explanations, no prose, only JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            try:
                response = await client.post(
                    f"{self.api_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error_msg = f"Groq API request failed: {exc.response.text}"
                logger.error(error_msg)
                raise HTTPException(
                    status_code=exc.response.status_code,
                    detail=error_msg,
                ) from exc
            except httpx.HTTPError as exc:
                error_msg = f"Failed to reach Groq API: {exc}"
                logger.error(error_msg)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=error_msg,
                ) from exc

        try:
            response_data = response.json()
            content = response_data["choices"][0]["message"]["content"]
            return content.strip()
        except (KeyError, IndexError) as exc:
            error_msg = "Unexpected Groq response structure."
            logger.error(f"{error_msg} Response: {response_data}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=error_msg,
            ) from exc


# Legacy function for backward compatibility
async def perform_template_extraction(
    *, full_text: str, word_list: list[Dict[str, Any]], template_json: Dict[str, Any]
) -> list[Dict[str, Any]]:
    """
    Legacy function for template extraction.
    Kept for backward compatibility.
    """
    service = GroqService()
    prompt = _build_prompt(full_text, word_list, template_json)
    content = await service.extract(prompt)
    parsed = _parse_structured_output(content)
    _validate_extracted_fields(parsed)
    return parsed


def _build_prompt(
    full_text: str, word_list: list[Dict[str, Any]], template_json: Dict[str, Any]
) -> str:
    """Build prompt for legacy extraction function."""
    template_block = json.dumps(template_json, ensure_ascii=False, indent=2)
    words_block = json.dumps(word_list, ensure_ascii=False)
    prompt_parts = [
        "Perform template-based extraction using the provided template.",
        "Return a JSON array of objects with keys 'key', 'value', and 'line_indexes'.",
        "line_indexes must be the integer line numbers where the value appears.",
        "Do not include any additional commentary.",
        "\nTemplate JSON:\n" + template_block,
        "\nFull Text:\n" + full_text,
        "\nWord List JSON:\n" + words_block,
    ]
    return "\n".join(prompt_parts)


def _parse_structured_output(content: str) -> list[Dict[str, Any]]:
    """Parse structured output from legacy function."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        segments = cleaned.split("```")
        for segment in segments:
            segment = segment.strip()
            if not segment or segment in {"json", "JSON"}:
                continue
            cleaned = segment
            break

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Groq response is not valid JSON: {exc}") from exc

    if isinstance(data, dict) and "results" in data:
        data = data["results"]

    if not isinstance(data, list):
        raise ValueError("Groq response must be a JSON array.")

    return data


def _validate_extracted_fields(data: list[Dict[str, Any]]) -> None:
    """Validate extracted fields from legacy function."""
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each extracted field must be a JSON object.")
        for key in ("key", "value", "line_indexes"):
            if key not in item:
                raise ValueError(f"Missing '{key}' in extracted field.")
        item["key"] = str(item["key"])
        item["value"] = str(item["value"])
        if not isinstance(item["line_indexes"], list):
            raise ValueError("line_indexes must be a list of integers.")
        item["line_indexes"] = [int(idx) for idx in item["line_indexes"]]
