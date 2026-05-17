from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from libs import cache, history
from libs.image_loader import ImageLoadError, load
from libs.vision_client import call_vision
from services.artwork.schemas import AnalyzeRequest, ArtworkResult

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("artwork")

PROMPT_PATH = Path(__file__).parent / "prompts" / "artwork_v1.md"
PROMPT_VERSION = "artwork_v1"

app = FastAPI(title="Weybees Artwork Service", version="1.0.0")


def _load_prompt() -> tuple[str, str]:
    """Read the prompt file and split it into (system, user) sections."""
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    system_marker = "## SYSTEM"
    user_marker = "## USER INSTRUCTION"
    system_start = raw.index(system_marker) + len(system_marker)
    user_start = raw.index(user_marker)
    system = raw[system_start:user_start].strip()
    user = raw[user_start + len(user_marker):].strip()
    return system, user


SYSTEM_PROMPT, USER_PROMPT = _load_prompt()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check; also reports the active prompt version for debugging."""
    return {"status": "ok", "prompt_version": PROMPT_VERSION}


@app.post("/analyze", response_model=ArtworkResult)
async def analyze(req: AnalyzeRequest) -> ArtworkResult:
    """Analyse one artwork image and return {keywords, caption, description}."""
    try:
        img = await load(req.image)
    except ImageLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    cache_key = cache.make_key("artwork", PROMPT_VERSION, img.sha256)
    cached = await cache.get_json(cache_key)
    if cached:
        log.info("cache hit sha=%s", img.sha256)
        return ArtworkResult(**cached)

    result = await call_vision(
        system=SYSTEM_PROMPT,
        user_text=USER_PROMPT,
        images=[img],
    )

    try:
        payload = result.as_json()
        validated = ArtworkResult(**payload)
    except Exception as exc:
        log.error("schema validation failed: %s | raw=%s", exc, result.text[:400])
        raise HTTPException(status_code=502, detail=f"invalid model output: {exc}")

    serialized = validated.model_dump()
    await cache.set_json(cache_key, serialized)
    history.record("artwork", img.sha256, serialized)
    return validated
