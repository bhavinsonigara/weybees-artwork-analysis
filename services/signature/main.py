from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from libs import cache, history
from libs.image_loader import ImageLoadError, LoadedImage, load
from libs.vision_client import call_vision
from services.signature.schemas import ExtractRequest, ExtractResponse, Signature

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("signature")

PROMPTS_DIR = Path(__file__).parent / "prompts"
EXTRACT_VERSION = "extract_text_v1"
CLASSIFY_VERSION = "classify_signature_v1"

app = FastAPI(title="Weybees Signature Service", version="1.0.0")


def _split(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    s_marker, u_marker = "## SYSTEM", "## USER INSTRUCTION"
    s_start = raw.index(s_marker) + len(s_marker)
    u_start = raw.index(u_marker)
    return raw[s_start:u_start].strip(), raw[u_start + len(u_marker):].strip()


EXTRACT_SYSTEM, EXTRACT_USER = _split(PROMPTS_DIR / "extract_text_v1.md")
CLASSIFY_SYSTEM, CLASSIFY_USER = _split(PROMPTS_DIR / "classify_signature_v1.md")


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "extract_prompt": EXTRACT_VERSION,
        "classify_prompt": CLASSIFY_VERSION,
    }


@app.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    loaded: list[LoadedImage] = []
    for src in req.images:
        try:
            loaded.append(await load(src))
        except ImageLoadError as exc:
            raise HTTPException(status_code=400, detail=f"image load failed: {exc}")

    results = await asyncio.gather(*[_process_image(i, img) for i, img in enumerate(loaded)])
    signatures: list[Signature] = []
    for batch in results:
        signatures.extend(batch)
    return ExtractResponse(signatures=signatures)


async def _process_image(index: int, img: LoadedImage) -> list[Signature]:
    cache_key = cache.make_key("signature", EXTRACT_VERSION, CLASSIFY_VERSION, img.sha256)
    cached = await cache.get_json(cache_key)
    if cached is not None:
        log.info("cache hit sha=%s", img.sha256)
        return [Signature(image_index=index, **entry) for entry in cached]

    regions = await _pass1_extract_regions(img)
    if not regions:
        log.info("pass1 found no text regions sha=%s", img.sha256)
        await cache.set_json(cache_key, [])
        history.record("signature", img.sha256, [])
        return []

    classified = await _pass2_classify(img, regions)
    entries = [
        {
            "signature_text": sig["signature_text"],
            "location_hint": sig["location_hint"],
            "confidence": float(sig["confidence"]),
        }
        for sig in classified
        if isinstance(sig, dict) and sig.get("signature_text")
    ]
    await cache.set_json(cache_key, entries)
    history.record("signature", img.sha256, entries)
    return [Signature(image_index=index, **entry) for entry in entries]


async def _pass1_extract_regions(img: LoadedImage) -> list[dict[str, Any]]:
    result = await call_vision(
        system=EXTRACT_SYSTEM,
        user_text=EXTRACT_USER,
        images=[img],
    )
    try:
        payload = result.as_json()
    except Exception as exc:
        log.error("pass1 parse failed: %s | raw=%s", exc, result.text[:400])
        raise HTTPException(status_code=502, detail=f"pass1 invalid output: {exc}")
    regions = payload.get("regions", []) if isinstance(payload, dict) else []
    return [r for r in regions if isinstance(r, dict) and r.get("text")]


async def _pass2_classify(img: LoadedImage, regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_prompt = (
        CLASSIFY_USER
        + "\n\n## TEXT REGIONS TO CLASSIFY\n\n```json\n"
        + json.dumps({"regions": regions}, ensure_ascii=False, indent=2)
        + "\n```\n"
    )
    result = await call_vision(
        system=CLASSIFY_SYSTEM,
        user_text=user_prompt,
        images=[img],
    )
    try:
        payload = result.as_json()
    except Exception as exc:
        log.error("pass2 parse failed: %s | raw=%s", exc, result.text[:400])
        raise HTTPException(status_code=502, detail=f"pass2 invalid output: {exc}")
    sigs = payload.get("signatures", []) if isinstance(payload, dict) else []
    return [s for s in sigs if isinstance(s, dict)]
