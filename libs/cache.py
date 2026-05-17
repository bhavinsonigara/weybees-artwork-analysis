from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis.asyncio as redis

log = logging.getLogger(__name__)

_TTL = int(os.getenv("VISION_CACHE_TTL_SECONDS", "2592000"))

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    """Return a process-wide async Redis client, creating it on first call."""
    global _client
    if _client is None:
        _client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    return _client


def make_key(namespace: str, *parts: str) -> str:
    """Build a colon-separated cache key under the `weybees:<namespace>:...` prefix."""
    return ":".join(("weybees", namespace, *parts))


async def get_json(key: str) -> Any | None:
    """Fetch and JSON-decode a cached value; return None on miss or error."""
    try:
        raw = await _get_client().get(key)
    except Exception as exc:
        log.warning("cache get failed key=%s err=%s", key, exc)
        return None
    return json.loads(raw) if raw else None


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    """JSON-encode and store a value under the key with the given TTL."""
    try:
        await _get_client().set(key, json.dumps(value), ex=ttl or _TTL)
    except Exception as exc:
        log.warning("cache set failed key=%s err=%s", key, exc)
