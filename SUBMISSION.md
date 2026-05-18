# Submission — AI-Powered Artwork Analysis

A complete walkthrough of what was built, how to run it, and how it maps to every requirement in the brief.

---

## What was built

Two independent AI vision pipelines delivered as a microservices demo:

| Task | Endpoint | Input | Output |
|---|---|---|---|
| **Task 1** — Artwork content extraction | `POST /task1/analyze` | One image (URL or base64) | `{keywords, caption, description}` |
| **Task 2** — Artist signature extraction | `POST /task2/extract` | One or more images | `[{signature_text, location_hint, confidence}, …]` |

Both pipelines are backed by **Google Gemini 2.5 Flash** (free tier), wrapped in FastAPI microservices, fronted by a single gateway, and cached with Redis so repeat evaluations don't re-hit the API.

---

## Repository layout

```
services/
  gateway/          Public entry point — routes, validates, normalises errors
  artwork/          Task 1 pipeline (single-pass JSON extraction)
  signature/        Task 2 pipeline (two-pass extract → classify)
libs/               Shared: image_loader, vision_client, cache, history
services/*/prompts/ Versioned prompt files (Markdown, not strings in code)
fixtures/           Six reference images committed for offline use
submission/         outputs.json — actual demo run results
tests/              Offline unit tests (no API key required)
scripts/            run_demo.py headless runner, fetch_fixtures.py
notebook/           demo.ipynb — interactive walkthrough
docs/               API reference, architecture, evaluation map, operations guide
DESIGN.md           Full design rationale and trade-off notes
```

---

## How to run it

### Prerequisites
- Docker Desktop (running)
- A free Google AI Studio API key: https://aistudio.google.com/app/apikey

### Setup

```bash
cp .env.example .env
# Open .env and set:  GEMINI_API_KEY=AIza...
```

> **Quota note:** New Google AI Studio projects start with a low daily quota on Gemini 2.5 Flash (~20 RPD). If you hit a 429 error, switch to the lite model in `.env`:
> ```
> GEMINI_MODEL=gemini-2.5-flash-lite
> ```
> The pipeline runs identically — only the OCR quality on highly stylised painted signatures is slightly lower.

### Start the stack

```bash
docker compose up --build
```

Wait for all four containers to report healthy, then verify:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "gateway": "ok",
  "artwork": { "status": "ok", "prompt_version": "artwork_v1" },
  "signature": { "status": "ok", "extract_prompt": "extract_text_v1", "classify_prompt": "classify_signature_v2" }
}
```

### Call the APIs

**Task 1** — analyse an artwork image:
```bash
curl -X POST http://localhost:8000/task1/analyze \
  -H "Content-Type: application/json" \
  -d '{"image": "https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg&height=1500&quality=90"}'
```

**Task 2** — extract signatures from multiple images:
```bash
curl -X POST http://localhost:8000/task2/extract \
  -H "Content-Type: application/json" \
  -d '{
    "images": [
      "https://taschen.makaira.media/taschen/image/upload/f_webp,w_1200/v1673610310/products-live/9573c6ba25c925247096b97703ae13f9.jpg",
      "https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg&height=1500&quality=90"
    ]
  }'
```

Both endpoints accept an `http(s)://` URL, a raw base64 string, or a `data:<mime>;base64,...` URI.

### Pre-built demo output

`submission/outputs.json` contains the actual output from a live run against all six fixture images (three images via Gemini 2.5 Flash, three via Flash Lite after the daily quota was exhausted). You can review it without starting the stack.

### Headless runner (re-run the full demo)

```bash
python scripts/run_demo.py
```

### Interactive notebook

```bash
pip install jupyter
jupyter notebook notebook/demo.ipynb
```

### Unit tests (no API key needed)

```bash
pip install -r requirements.txt
pytest
```

---

## How the pipelines work

### Task 1 — single-pass artwork extraction

```
client ──► gateway ──► artwork service
                           │
                    load & normalise image
                           │
                    Gemini 2.5 Flash (vision, JSON mode)
                    prompt: artwork_v1.md
                           │
                    Pydantic validation
                    (keywords 5-10, caption ≤20 words)
                           │
                    Redis cache write (TTL 30 days)
                           │◄── cache hit on repeat call
                    return {keywords, caption, description}
```

The prompt tells the model to derive everything from the visual content only — no filenames, auction metadata, or URLs are passed.

### Task 2 — two-pass signature extraction

```
client ──► gateway ──► signature service
                           │
                    load & normalise each image
                           │
              ┌──── for each image ────┐
              │                        │
              │  PASS 1 — extract_text_v1.md
              │  "Transcribe every text region you can see.
              │   Do NOT decide what is a signature yet."
              │  → JSON list of {text, location}
              │                        │
              │  PASS 2 — classify_signature_v2.md
              │  (original image + pass-1 list sent together)
              │  "Which of these regions is the artist's
              │   handwritten signature? Exclude: plate titles,
              │   edition numbers, dates, E.A., publisher names."
              │  → {signatures: [{text, location, confidence}]}
              │                        │
              └────────────────────────┘
                           │
                    merge all per-image results
                    return flat list of Signature objects
```

**Why two passes?** With a single prompt, models frequently return plate titles or edition numbers alongside the real signature when multiple text elements are present. Splitting the problem into "find all text" and "classify each piece" lets each prompt do one job and makes failures easy to localise.

**The brief's canary case** (David Hockney "My Window"): the image contains three text elements — `David Hockney` (the signature), `my Window` (the book title), and `Taschen` (the publisher). The classify prompt names all three types as explicit negative examples and includes a positive rule for artist-name-on-cover. In the committed output, only `David Hockney` is returned.

---

## How each brief requirement is met

### Task 1

| Requirement | How it is met |
|---|---|
| Input: image URL or base64 | `libs/image_loader.py` — URL fetch, raw base64, and `data:` URI all handled |
| Output: `keywords` (5-10 tags) | Enforced in prompt and by `ArtworkResult` Pydantic validator |
| Output: `caption` (≤20 words, one sentence) | Enforced in prompt and by `field_validator` in `services/artwork/schemas.py` |
| Output: `description` (3-5 sentences) | Enforced in prompt; model instructed: composition, technique, subject, mood |
| Derive from visual content only | Prompt rule: "Do not reference filenames, URLs, or any metadata" |
| Ignore watermarks / auction chrome | Prompt rule: "Ignore watermarks, logos, frame, mat" |
| Structured JSON output | Native JSON mode (`response_mime_type="application/json"`) + Pydantic validation |

### Task 2

| Requirement | How it is met |
|---|---|
| Input: list of image URLs or base64 | Same `image_loader` as Task 1, applied per-image |
| Output: `signature_text` (exact transcription) | Pass 1 transcribes verbatim; pass 2 preserves the text |
| Output: `location_hint` | Pass 1 records location; pass 2 enriches with visual context |
| Output: `confidence` (0.0 – 1.0) | Enforced by `Signature` Pydantic validator; bands defined in prompt |
| Exclude plate titles | Named in prompt: `"La Pythonisse"` |
| Exclude edition numbers | Named in prompt: `"147/280"` |
| Exclude dates | Named in prompt: `"1972"` |
| Exclude E.A. annotations | Named in prompt: `"E.A."` |
| Exclude pencil titles | Named in prompt: title vs. signature distinction |
| Exclude publisher names | Named in prompt: `"Taschen"` |
| Hockney "My Window" canary | classify_signature_v2 has explicit INCLUDE rule for artist-name-on-cover |
| List output, one entry per signature | `ExtractResponse.signatures: list[Signature]` |
| Per-image fault tolerance | Sequential loop with per-image `try/except` — one image error doesn't abort the batch |

---

## Important note — reference images

The brief's primary reference (Suduca Lot 242, `suduca.com/vente/tableaux-estampes-lot-242-2/`) was **recycled by the auction house** between the time the brief was written and the time of this submission. The URL now shows a completely different lot.

The six committed fixture images substitute comparable test cases that exercise the same pipeline paths:

| fixture | what it tests |
|---|---|
| `david_hockney_my_window.webp` | Brief's own canary — three text elements, must return only the artist name |
| `winter_in_the_land.jpg` (Bonhams) | Clean baseline — single painted signature, no other text |
| `yvon_grac_beach.jpg` | Painted signature in a busy composition (like a signed lithograph) |
| `yvon_grac_signature_closeup.jpg` | Signature fills the frame — high-confidence extraction |
| `yvon_grac_framed.jpg` | Gilded frame artefacts — frame text must be ignored |
| `seascape_monogram.jpg` | Low-legibility monogram — expected confidence ≤0.7 |

The Hockney and Bonhams images are from the brief's own reference list and are intact. Task 1 runs on the Yvon GRAC beach scene as a stand-in for the Guy DUC lithograph.

---

## Key design decisions (summary)

Full rationale in `DESIGN.md`. Short version:

| decision | reason |
|---|---|
| Gemini 2.5 Flash (free tier) | Best noise rejection + OCR quality available at zero cost |
| `thinking_budget=0` | Gemini 2.5 thinking tokens truncated JSON output; disabling them fixes it |
| Two-pass signature pipeline | Single-pass models over-include plate titles; splitting extraction from classification fixes the hard cases |
| Versioned prompt files | Cache key includes prompt version — bumping the prompt auto-invalidates Redis without manual flush |
| Provider isolated to one file | Swapping Gemini for Claude/GPT-4o is a single-file change; services and prompts are untouched |
| Sequential per-image processing | `asyncio.gather` burst past Gemini's RPM=5 limit; sequential loop with per-image error isolation is safer |

---

## Further reading

- `DESIGN.md` — full trade-off notes, model comparison table, deliberate omissions
- `docs/API.md` — complete endpoint reference with request/response examples
- `docs/ARCHITECTURE.md` — architecture diagram, request flow, cache key design
- `docs/EVALUATION.md` — maps every brief evaluation criterion to the specific file/behaviour that demonstrates it
- `docs/OPERATIONS.md` — troubleshooting guide (every real error hit during development, with the actual fix)
- `http://localhost:8000/docs` — auto-generated Swagger UI (requires running stack)
