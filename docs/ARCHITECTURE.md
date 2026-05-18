# Architecture

A small microservices stack that exposes two AI vision pipelines behind one HTTP gateway. Three FastAPI services + Redis + SQLite, orchestrated with Docker Compose. See [DESIGN.md](../DESIGN.md) for the *why* behind every choice; this document is the structural reference.

## High-level diagram

```
                              ┌─────────────────────┐
                              │     HTTP client     │
                              │ (curl / notebook /  │
                              │  scripts/run_demo)  │
                              └──────────┬──────────┘
                                         │ JSON
                                         ▼
                              ┌─────────────────────┐
                              │   gateway  :8000    │
                              │   (FastAPI)         │
                              │  ┌───────────────┐  │
                              │  │ pydantic in   │  │
                              │  │ route + proxy │  │
                              │  │ pydantic out  │  │
                              │  └───────────────┘  │
                              └──────┬───────┬──────┘
                                     │       │
                ┌────────────────────┘       └────────────────────┐
                │                                                 │
                ▼                                                 ▼
   ┌─────────────────────────┐                       ┌─────────────────────────┐
   │   artwork  :8001        │                       │   signature  :8002      │
   │   (FastAPI, Task 1)     │                       │   (FastAPI, Task 2)     │
   │                         │                       │                         │
   │  POST /analyze          │                       │  POST /extract          │
   │  ─ single-pass prompt   │                       │  ─ two-pass pipeline:   │
   │    artwork_v1.md        │                       │      extract_text_v1    │
   │  ─ ArtworkResult        │                       │    → classify_sig_v2    │
   │    Pydantic schema      │                       │  ─ sequential per-image │
   └────────┬────────────────┘                       │  ─ per-image try/except │
            │                                        └────────┬────────────────┘
            │                                                 │
            └───────────────┬─────────────────────────────────┘
                            │
                            ▼
        ┌────────────────────────────────────────┐
        │ libs/  (shared, in every service image)│
        │ ──────────────────────────────────────│
        │ image_loader.py  URL/base64 → bytes   │
        │                  resize, SHA-256      │
        │ vision_client.py google-genai wrapper │
        │                  JSON mode, no think  │
        │ cache.py         Redis async client   │
        │ history.py       SQLite audit log     │
        └────────┬───────────────────┬──────────┘
                 │                   │
                 ▼                   ▼
        ┌─────────────────┐  ┌─────────────────┐
        │ Redis  :6379    │  │ SQLite          │
        │ vision-call     │  │ ./data/         │
        │ cache by        │  │   history.sqlite│
        │ {ns}:{prompt}:  │  │ analyses(id,    │
        │  {sha256}       │  │   task, sha,    │
        │                 │  │   result_json)  │
        └─────────────────┘  └─────────────────┘
                 ▲
                 │ all vision calls also go out to:
                 ▼
        ┌─────────────────────────────┐
        │  generativelanguage.        │
        │  googleapis.com (Gemini)    │
        └─────────────────────────────┘
```

## Service responsibilities

| service | port | endpoints | what it owns |
|---|---|---|---|
| **gateway** | 8000 | `GET /health`, `POST /task1/analyze`, `POST /task2/extract` | The only public surface. Validates request bodies with Pydantic. Aggregates downstream health. Forwards errors with a normalised envelope. |
| **artwork** | 8001 | `GET /health`, `POST /analyze` | Task 1 (single-image content extraction). Owns `prompts/artwork_v1.md` and `schemas.ArtworkResult`. |
| **signature** | 8002 | `GET /health`, `POST /extract` | Task 2 (signature extraction). Owns the two prompt files and runs the pass1→pass2 pipeline. Sequential per-image with per-image try/except so partial failures don't poison the batch. |
| **redis** | 6379 | — | Caches vision-call results keyed by `weybees:{namespace}:{prompt_version}:{image_sha256}`. Prompt-version in the key means a prompt bump auto-invalidates. |
| **SQLite** | — | — | Audit log of every successful analysis (one row per task per image), at `./data/history.sqlite3` (volume mount). |

## Request flow — Task 1 (artwork analysis)

```
client → POST /task1/analyze {"image": <url or base64>}
       → gateway validates Task1Request (pydantic)
       → gateway forwards to http://artwork:8001/analyze
           → image_loader.load(source)            ← URL fetch / base64 decode / resize / SHA
           → cache.get_json(weybees:artwork:artwork_v1:<sha>)
                ├── hit → return ArtworkResult, end
                └── miss → vision_client.call_vision(system, user, [image])
                           ├── Gemini returns JSON {keywords, caption, description}
                           ├── ArtworkResult(**parsed)  ← pydantic validates structure
                           │   ├── 5-10 keywords
                           │   └── caption ≤20 words
                           ├── cache.set_json(...)
                           └── history.record("artwork", sha, result)
       → response → client
```

## Request flow — Task 2 (signature extraction)

```
client → POST /task2/extract {"images": [...]}
       → gateway validates Task2Request (pydantic)
       → gateway forwards to http://signature:8002/extract
           → for each image src:
               image_loader.load(src)             ← raises 400 if any image is unloadable
           → for each loaded image (SEQUENTIAL, with try/except per image):
               ┌─── cache.get_json(weybees:signature:extract_v1:classify_v2:<sha>)
               │     hit → emit cached Signatures
               │     miss ↓
               │
               │   PASS 1 — vision_client.call_vision(extract_text_v1, image)
               │     ├── Gemini returns {"regions": [{text, location, appearance}, ...]}
               │     └── filter to regions with non-empty text
               │
               │   if no regions: cache empty, record, continue
               │
               │   PASS 2 — vision_client.call_vision(
               │              classify_signature_v2,
               │              image + JSON(regions))
               │     ├── Gemini returns {"signatures": [{signature_text, location_hint, confidence}, ...]}
               │     ├── Signature(**entry)  ← pydantic validates 0.0 ≤ confidence ≤ 1.0
               │     ├── cache.set_json(...)
               │     └── history.record(...)
               └────
           → ExtractResponse(signatures=[...])
       → response → client
```

## Why two-pass for Task 2

A single combined "find and classify signatures" prompt routinely either over-includes (returns titles and edition numbers as signatures) or over-excludes (returns nothing on the Hockney book-cover canary). Splitting the work into two passes:

1. **Pass 1 is exhaustive, not interpretive.** It surfaces every text region — signature, title, edition number, date, stamp, publisher imprint — exactly as transcribed. The model is explicitly told it is NOT deciding what's a signature.

2. **Pass 2 is purely a classifier.** It receives the image AND the pass-1 region list, then decides one-at-a-time. Negative examples for the brief's hard cases (`La Pythonisse`, `147/280`, `1972`, `E.A.`, `Taschen`) are named in the prompt. Positive examples (Hockney case) are also named.

Cost: 2× vision calls per image. Mitigated by the Redis cache; repeated requests are free. Failures are localisable to the specific pass.

See `services/signature/prompts/extract_text_v1.md` and `classify_signature_v2.md` for the actual prompts.

## Provider boundary

The Gemini SDK is touched in exactly one file: `libs/vision_client.py` (~80 lines). Services call `await call_vision(system=..., user_text=..., images=[...])` and get back `VisionResult(text, input_tokens, output_tokens)`. Swapping to Claude, GPT-4o, or a self-hosted model is a single-file change. The provider boundary is deliberately the thinnest seam in the system.

## Cache key design

```
weybees:{namespace}:{prompt_version[, ...]}:{image_sha256_of_normalised_bytes}
```

- **`namespace`** — `artwork` or `signature`, so the two pipelines never collide.
- **`prompt_version`** — bumping a prompt file (`classify_signature_v2` → `_v3`) auto-invalidates that prompt's cached results without a manual flush. Multiple versions in the key for the two-pass pipeline (`extract_v1:classify_v2`) so a change to either invalidates.
- **`image_sha256`** — computed on the *normalised* bytes (after resize / re-encode), so the same image fetched via two different URLs hits the same key.

What is NOT in the key right now: the model id. A model swap mid-run would return previously-cached results from a different model. For this demo we manage that explicitly (the `model` tag in `submission/outputs.json` is preserved from prior runs by `scripts/run_demo.py`). For production use the cleanest fix would be to add `model_id` to the namespace.

## Storage

- **Redis** — ephemeral cache, 30-day TTL by default (configurable via `VISION_CACHE_TTL_SECONDS`). Container is volumeless; restarts wipe it. That's fine for a demo.
- **SQLite** — host-mounted at `./data/history.sqlite3` (via the `volumes:` entry in `docker-compose.yml`). Survives container recreates. Schema in `libs/history.py`.

Both are non-fatal: cache failures are logged and the request still computes; history failures are logged and the request still returns.
