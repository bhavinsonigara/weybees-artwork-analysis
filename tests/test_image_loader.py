import base64
import io

import pytest
from PIL import Image

from libs.image_loader import ImageLoadError, MAX_DIMENSION, load


def _png_bytes(size=(64, 64), color=(120, 50, 200)) -> bytes:
    """Generate an in-memory PNG of the given size and colour for tests."""
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_load_base64_png():
    """load() accepts raw base64 input and returns a hash-able LoadedImage."""
    data = _png_bytes()
    payload = base64.b64encode(data).decode("ascii")
    img = await load(payload)
    assert img.media_type in {"image/png", "image/jpeg"}
    assert len(img.sha256) == 64


@pytest.mark.asyncio
async def test_load_data_uri():
    """load() accepts a `data:image/png;base64,...` URI."""
    data = _png_bytes()
    payload = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    img = await load(payload)
    assert img.sha256


@pytest.mark.asyncio
async def test_load_rejects_garbage():
    """load() raises ImageLoadError for input that is neither a URL nor valid base64."""
    with pytest.raises(ImageLoadError):
        await load("not-a-real-base64-payload!!!")


@pytest.mark.asyncio
async def test_load_downscales_oversized_image():
    """load() resizes an image whose longest side exceeds MAX_DIMENSION."""
    data = _png_bytes(size=(MAX_DIMENSION * 2, MAX_DIMENSION * 2))
    payload = base64.b64encode(data).decode("ascii")
    img = await load(payload)
    assert img.media_type == "image/jpeg"
    with Image.open(io.BytesIO(img.data)) as im:
        assert max(im.size) <= MAX_DIMENSION
