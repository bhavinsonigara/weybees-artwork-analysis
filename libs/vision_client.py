from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from libs.image_loader import LoadedImage

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
DEFAULT_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "4096"))
# Gemini 2.5 models burn output tokens on hidden "thinking" before the visible
# response. For deterministic structured-JSON tasks like ours we want every
# output token spent on the JSON itself, so disable thinking explicitly.
DISABLE_THINKING = os.getenv("GEMINI_DISABLE_THINKING", "1") != "0"

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


@dataclass
class VisionResult:
    text: str
    input_tokens: int
    output_tokens: int

    def as_json(self) -> Any:
        return _extract_json(self.text)


async def call_vision(
    *,
    system: str,
    user_text: str,
    images: list[LoadedImage],
    model: str | None = None,
    max_tokens: int | None = None,
) -> VisionResult:
    client = _get_client()
    parts: list[Any] = [
        types.Part.from_bytes(data=img.data, mime_type=img.media_type) for img in images
    ]
    parts.append(user_text)

    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "max_output_tokens": max_tokens or DEFAULT_MAX_TOKENS,
    }
    if DISABLE_THINKING:
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass
    config = types.GenerateContentConfig(**config_kwargs)

    model_id = model or DEFAULT_MODEL
    response = await client.aio.models.generate_content(
        model=model_id,
        contents=parts,
        config=config,
    )

    text = (response.text or "").strip()
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    log.info(
        "vision_call model=%s input_tokens=%d output_tokens=%d",
        model_id,
        input_tokens,
        output_tokens,
    )
    return VisionResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens)


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    match = _JSON_FENCE.search(text)
    candidate = match.group(1) if match else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start_obj = candidate.find("{")
        start_arr = candidate.find("[")
        starts = [s for s in (start_obj, start_arr) if s != -1]
        if not starts:
            raise
        start = min(starts)
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if end <= start:
            raise
        return json.loads(candidate[start : end + 1])
