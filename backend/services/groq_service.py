import json
import os
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, status


GROQ_API_BASE_URL = os.getenv("GROQ_API_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")


async def perform_template_extraction(
    *, full_text: str, word_list: List[Dict[str, Any]], template_json: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GROQ_API_KEY is not configured.",
        )

    input_payload = {
        "model": GROQ_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise information extraction assistant. "
                    "Extract the requested fields and return ONLY valid JSON."
                ),
            },
            {
                "role": "user",
                "content": _build_prompt(full_text, word_list, template_json),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        try:
            response = await client.post(
                f"{GROQ_API_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=input_payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Groq extraction failed: {exc.response.text}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reach Groq API: {exc}",
            ) from exc

    response_payload = response.json()
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected Groq response structure.",
        ) from exc

    parsed = _parse_structured_output(content)
    _validate_extracted_fields(parsed)
    return parsed


def _build_prompt(
    full_text: str, word_list: List[Dict[str, Any]], template_json: Dict[str, Any]
) -> str:
    template_block = json.dumps(template_json, ensure_ascii=False, indent=2)
    words_block = json.dumps(word_list, ensure_ascii=False)
    prompt_parts = [
        "Perform template-based extraction using the provided template.",
        "Return a JSON array of objects with keys 'key', 'value', and 'word_indexes'.",
        "word_indexes must be the integer indexes from the supplied word list.",
        "Do not include any additional commentary.",
        "\nTemplate JSON:\n" + template_block,
        "\nFull Text:\n" + full_text,
        "\nWord List JSON:\n" + words_block,
    ]
    return "\n".join(prompt_parts)


def _parse_structured_output(content: str) -> List[Dict[str, Any]]:
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


def _validate_extracted_fields(data: List[Dict[str, Any]]) -> None:
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each extracted field must be a JSON object.")
        for key in ("key", "value", "word_indexes"):
            if key not in item:
                raise ValueError(f"Missing '{key}' in extracted field.")
        item["key"] = str(item["key"])
        item["value"] = str(item["value"])
        if not isinstance(item["word_indexes"], list):
            raise ValueError("word_indexes must be a list of integers.")
        item["word_indexes"] = [int(idx) for idx in item["word_indexes"]]
