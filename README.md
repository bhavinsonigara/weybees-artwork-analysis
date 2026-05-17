# Weybees Artwork Analysis

Two AI-powered vision pipelines for fine-art auction images, packaged as a small microservices demo.

- **Task 1 — Artwork content extraction**: given one image, return `{keywords, caption, description}`.
- **Task 2 — Signature extraction**: given one or more images, return a list of `{signature_text, location_hint, confidence}`, filtering out plate titles, edition numbers, dates, annotations, and publisher names.

See [DESIGN.md](DESIGN.md) for the design rationale (model choice, prompt structure, two-pass classifier, trade-offs).

## Architecture

```
client ── HTTP ──► gateway ──┬──► artwork service   (Task 1)
                             └──► signature service (Task 2)
                                         │
                                  Redis cache (vision call results)
                                  SQLite history (audit log)
```

Each service is its own FastAPI app, its own container, and owns its prompts. Shared concerns (image loading, vision-model client, cache, history) live in `libs/`.

## Quickstart

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...

docker compose up --build
```

Health check once it's up:

```bash
curl http://localhost:8000/health
```

### Task 1 — analyze a single artwork

```bash
curl -X POST http://localhost:8000/task1/analyze \
  -H "Content-Type: application/json" \
  -d '{"image":"https://www.suduca.com/wp-content/uploads/2024/05/IMG_2864-scaled.jpg"}'
```

Example response:

```json
{
  "keywords": ["lithograph", "mysticism", "monochrome", "robed figure", "1970s", "french", "fine art print"],
  "caption": "A robed mystical figure rendered in stark monochrome lithograph.",
  "description": "A central robed figure dominates the composition ..."
}
```

### Task 2 — extract signatures across multiple images

```bash
curl -X POST http://localhost:8000/task2/extract \
  -H "Content-Type: application/json" \
  -d '{
        "images": [
          "https://www.suduca.com/wp-content/uploads/2024/05/IMG_2864-scaled.jpg",
          "https://www.suduca.com/wp-content/uploads/2024/05/IMG_2865-scaled.jpg",
          "https://upload.wikimedia.org/wikipedia/en/2/2d/David_Hockney_My_Window.jpg"
        ]
      }'
```

Example response:

```json
{
  "signatures": [
    {"image_index": 0, "signature_text": "Guy Duc",        "location_hint": "lower right, pencil, below image margin", "confidence": 0.92},
    {"image_index": 1, "signature_text": "M. J. Llorca",   "location_hint": "lower left, pencil, below image margin",  "confidence": 0.88},
    {"image_index": 2, "signature_text": "David Hockney",  "location_hint": "upper area, blue handwritten lettering",  "confidence": 0.95}
  ]
}
```

Both endpoints accept either a URL or a base64-encoded image (raw base64 or a `data:image/...;base64,...` URI).

## Demo notebook

```bash
pip install jupyter
jupyter notebook notebook/demo.ipynb
```

The notebook hits the running gateway and exercises every image in `fixtures/` (six images, each probing a different signature failure mode). Inputs are sent as base64 data URIs from disk, so the demo is reproducible even if the original auction URLs change. See `fixtures/README.md` for what each fixture tests.

## Tests

```bash
pip install -r requirements.txt
pytest
```

The unit tests cover schema contracts, image loading (URL/base64/normalization), and JSON extraction from model output. They do **not** call the vision API.

## Environment variables

See `.env.example`. Key ones:

| var | purpose |
|---|---|
| `ANTHROPIC_API_KEY` | required, your Anthropic key |
| `ANTHROPIC_MODEL`   | defaults to `claude-sonnet-4-6` |
| `REDIS_URL`         | Redis connection string (auto-set inside Docker) |
| `SQLITE_PATH`       | Where the audit DB lives (auto-set inside Docker) |
| `VISION_CACHE_TTL_SECONDS` | how long cached vision results live; defaults to 30 days |

## Repository layout

```
services/
  gateway/         FastAPI router, calls the two backends
  artwork/         Task 1 — single-pass content extraction
  signature/       Task 2 — two-pass extract → classify pipeline
libs/              vision_client, image_loader, cache, history
tests/             pytest unit tests
scripts/           fetch_fixtures.py for offline image cache
notebook/          demo.ipynb
.claude/agents/    project-scoped Claude Code agents (tester, prompt-engineer, demo-runner)
```
