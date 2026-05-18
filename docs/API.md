# API Reference

The public surface is the **gateway** on `http://localhost:8000`. The artwork (`8001`) and signature (`8002`) services are reachable directly during development but should be considered internal.

A live interactive Swagger UI is also available at `http://localhost:8000/docs` once the stack is running (FastAPI auto-generates it from the Pydantic schemas).

---

## `GET /health`

Aggregate health probe. Returns the gateway's status plus a snapshot of each backend service's `/health` (including the active prompt versions, useful when iterating).

**Response — 200 OK**

```json
{
  "gateway": "ok",
  "artwork": {
    "status": "ok",
    "prompt_version": "artwork_v1"
  },
  "signature": {
    "status": "ok",
    "extract_prompt": "extract_text_v1",
    "classify_prompt": "classify_signature_v2"
  }
}
```

If a backend is unreachable the field becomes `"unreachable: <error>"` instead of a nested object — the gateway itself still returns 200 so a load balancer can decide what to do.

**Example**

```bash
curl http://localhost:8000/health
```

---

## `POST /task1/analyze`

Task 1 — analyse one artwork image and return structured descriptive metadata derived from the visual content only.

**Request body**

| field | type | required | description |
|---|---|---|---|
| `image` | string | yes | Either an `http(s)://...` URL **or** a raw base64 string **or** a `data:<mime>;base64,...` URI. |

**Response — 200 OK** (`ArtworkResult`)

| field | type | constraints |
|---|---|---|
| `keywords` | `string[]` | 5–10 non-empty tags (subject, style, medium, mood, era) |
| `caption` | `string` | one sentence, **≤ 20 words** |
| `description` | `string` | 3–5 sentences (composition, technique, subject, mood, notable details) |

**Error responses**

| status | when |
|---|---|
| `400 Bad Request` | image couldn't be loaded (bad URL, malformed base64, unsupported format) |
| `502 Bad Gateway` | model returned a payload that fails Pydantic validation (e.g. caption > 20 words, missing field) |

**Example**

```bash
curl -X POST http://localhost:8000/task1/analyze \
  -H "Content-Type: application/json" \
  -d '{"image":"https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg&height=1500&quality=90"}'
```

**Example response**

```json
{
  "keywords": ["portrait", "man", "winter scene", "indigenous", "horse",
               "teepees", "oil painting", "figurative", "cold weather"],
  "caption": "A man in traditional attire, wrapped in an orange blanket, stands in a snowy landscape with a horse and teepees.",
  "description": "This vertical oil painting depicts a full-length portrait of a man standing in a snow-covered environment. He wears a purple tunic, a white fringed skirt, tan moccasins and leggings, and a vibrant orange blanket. Behind him, two teepees are visible among snow-dusted trees, with a brown horse to the right. The artist uses visible brushstrokes, particularly in the snowy foreground and background, to create a textured and atmospheric winter scene."
}
```

---

## `POST /task2/extract`

Task 2 — extract artist signatures from one or more images, filtering out non-signature text (plate titles, edition numbers, dates, annotations, publisher names).

**Request body**

| field | type | required | description |
|---|---|---|---|
| `images` | `string[]` | yes, ≥1 | List of image URLs / base64 payloads / data URIs. Each is processed independently. |

**Response — 200 OK** (`ExtractResponse`)

```jsonc
{
  "signatures": [
    {
      "image_index": 0,             // 0-based index into the request's `images` array
      "signature_text": "...",       // exact transcription, capitalisation preserved
      "location_hint": "...",        // e.g. "lower right, pencil, below image margin"
      "confidence": 0.92             // 0.0 - 1.0, calibrated per classify_signature_v2.md
    }
  ]
}
```

An image may legitimately produce **0, 1, or N** signature entries depending on what's in it. Empty list means the model found no candidate it could classify with confidence ≥ 0.5.

**Per-image fault tolerance**: the signature service processes each image inside its own `try/except`. A failure on image *k* (e.g. a 429 from Gemini that can't be retried in time) is logged but doesn't poison the batch — the other images still return. To distinguish "model returned empty" from "image errored", check whether the image's index appears in `signatures` at all. The headless runner `scripts/run_demo.py` adds an explicit `errors[]` entry for any missing index.

**Error responses**

| status | when |
|---|---|
| `400 Bad Request` | any image in the list couldn't be loaded |
| `502 Bad Gateway` | pass 1 or pass 2 returned a payload that couldn't be parsed as JSON |

**Example**

```bash
curl -X POST http://localhost:8000/task2/extract \
  -H "Content-Type: application/json" \
  -d '{
        "images": [
          "https://upload.wikimedia.org/wikipedia/en/2/2d/David_Hockney_My_Window.jpg",
          "https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg"
        ]
      }'
```

**Example response**

```json
{
  "signatures": [
    {
      "image_index": 0,
      "signature_text": "David Hockney",
      "location_hint": "upper left of the front cover, handwritten-style, multicolored",
      "confidence": 0.9
    },
    {
      "image_index": 1,
      "signature_text": "W.A. GOMEZ",
      "location_hint": "lower right, painted brush signature in red",
      "confidence": 0.95
    }
  ]
}
```

The Hockney response demonstrates the brief's noise-rejection requirement — `David Hockney` is returned, while the book's title `my Window` and publisher imprint `Taschen` are excluded.

---

## Schemas (Pydantic source)

The wire schemas are enforced at the gateway boundary by Pydantic. Source files:

- `services/artwork/schemas.py` — `AnalyzeRequest`, `ArtworkResult`
- `services/signature/schemas.py` — `ExtractRequest`, `Signature`, `ExtractResponse`

Bad inputs get `422 Unprocessable Entity` from FastAPI with a structured error body identifying the failing field. Outputs that fail schema validation produce `502 Bad Gateway` (the model is "external" to us).
