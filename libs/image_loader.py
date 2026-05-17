from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass

import httpx
from PIL import Image

MAX_BYTES = 5 * 1024 * 1024
MAX_DIMENSION = 1568
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class ImageLoadError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedImage:
    data: bytes
    media_type: str
    sha256: str

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


async def load(source: str) -> LoadedImage:
    if source.startswith(("http://", "https://")):
        data, media_type = await _fetch_url(source)
    else:
        data, media_type = _decode_base64(source)

    data, media_type = _normalize(data, media_type)
    sha = hashlib.sha256(data).hexdigest()
    return LoadedImage(data=data, media_type=media_type, sha256=sha)


async def _fetch_url(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "WeybeesArtworkBot/1.0"})
        resp.raise_for_status()
        media_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type not in ALLOWED_MEDIA_TYPES:
            media_type = _sniff_media_type(resp.content)
        return resp.content, media_type


def _decode_base64(source: str) -> tuple[bytes, str]:
    payload = source
    media_type = "image/jpeg"
    if source.startswith("data:"):
        header, _, payload = source.partition(",")
        media_type = header[5:].split(";")[0] or "image/jpeg"
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ImageLoadError(f"invalid base64 payload: {exc}") from exc
    if media_type not in ALLOWED_MEDIA_TYPES:
        media_type = _sniff_media_type(data)
    return data, media_type


def _sniff_media_type(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").lower()
    except Exception as exc:
        raise ImageLoadError(f"unrecognized image data: {exc}") from exc
    mapping = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
    if fmt not in mapping:
        raise ImageLoadError(f"unsupported image format: {fmt}")
    return mapping[fmt]


def _normalize(data: bytes, media_type: str) -> tuple[bytes, str]:
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ImageLoadError(f"could not decode image: {exc}") from exc

    width, height = im.size
    longest = max(width, height)
    needs_resize = longest > MAX_DIMENSION
    needs_recompress = len(data) > MAX_BYTES

    if not needs_resize and not needs_recompress and media_type in ALLOWED_MEDIA_TYPES:
        return data, media_type

    if needs_resize:
        scale = MAX_DIMENSION / longest
        im = im.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), "image/jpeg"
