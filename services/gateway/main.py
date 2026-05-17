from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("gateway")

ARTWORK_URL = os.getenv("ARTWORK_SERVICE_URL", "http://artwork:8001")
SIGNATURE_URL = os.getenv("SIGNATURE_SERVICE_URL", "http://signature:8002")

app = FastAPI(title="Weybees Artwork Analysis Gateway", version="1.0.0")


class Task1Request(BaseModel):
    """Request body for /task1/analyze — a single image URL or base64 payload."""

    image: str = Field(..., description="Image URL or base64-encoded payload")


class Task2Request(BaseModel):
    """Request body for /task2/extract — a non-empty list of image URLs / base64 payloads."""

    images: list[str] = Field(..., min_length=1)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Aggregate health: returns gateway status plus each backend service's /health."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        results: dict[str, Any] = {"gateway": "ok"}
        for name, url in (("artwork", ARTWORK_URL), ("signature", SIGNATURE_URL)):
            try:
                r = await client.get(f"{url}/health")
                results[name] = r.json() if r.status_code == 200 else f"unhealthy ({r.status_code})"
            except Exception as exc:
                results[name] = f"unreachable: {exc}"
    return results


@app.post("/task1/analyze")
async def task1(req: Task1Request) -> JSONResponse:
    """Proxy a Task 1 request to the artwork service and return its JSON response."""
    return await _proxy(f"{ARTWORK_URL}/analyze", req.model_dump())


@app.post("/task2/extract")
async def task2(req: Task2Request) -> JSONResponse:
    """Proxy a Task 2 request to the signature service and return its JSON response."""
    return await _proxy(f"{SIGNATURE_URL}/extract", req.model_dump())


async def _proxy(url: str, payload: dict[str, Any]) -> JSONResponse:
    """POST a JSON payload to an upstream service and forward its response or error."""
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        log.error("upstream call failed url=%s err=%s", url, exc)
        raise HTTPException(status_code=502, detail=f"upstream unreachable: {exc}")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=detail)
    return JSONResponse(content=r.json(), status_code=200)
