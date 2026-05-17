from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from libs.image_loader import LoadedImage

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2048"))

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


@dataclass
class VisionResult:
    text: str
    input_tokens: int
    output_tokens: int

    def as_json(self) -> dict[str, Any]:
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
    content: list[dict[str, Any]] = []
    for img in images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type,
                    "data": img.base64,
                },
            }
        )
    content.append({"type": "text", "text": user_text})

    resp = await client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": content}],
    )

    text_parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
    text = "".join(text_parts).strip()

    usage = resp.usage
    log.info(
        "vision_call model=%s input_tokens=%d output_tokens=%d",
        resp.model,
        usage.input_tokens,
        usage.output_tokens,
    )
    return VisionResult(text=text, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)


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
