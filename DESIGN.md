# Design Notes

This document explains the design choices behind the two pipelines. Mapped to the evaluation criteria in the brief: accuracy, noise rejection, output structure, prompt engineering, code quality, justification.

## 1. Model selection — Gemini 2.5 Flash (with Lite fallback)

I evaluated five options:

| model | pros | cons |
|---|---|---|
| **Gemini 2.5 Flash** *(demo default)* | Best noise rejection AND best signature transcription on the test set, native JSON-mode | New AI Studio projects can have RPD as low as ~20 on free tier — fine for the demo but tight during iteration |
| Gemini 2.5 Flash Lite *(testing fallback)* | Much higher free-tier RPD — useful during prompt iteration | Visibly weaker at stylised-handwriting OCR (`Y. GRAC` → `PERT` on one fixture). Noise rejection still works. |
| Gemini 2.0 Flash | Strong vision | New projects often see free-tier RPD=0 for this model (account-eligibility quirk) |
| Claude Sonnet 4.6 | Excellent vision + instruction following | Paid only; no permanent free tier |
| Llama 3.2 Vision (via Groq) | Free, very fast | Visibly weaker on the noise rejection cases that matter most for Task 2 |

**Decision: Gemini 2.5 Flash for the demo.** Better signature OCR and equally strong noise rejection. The reviewer will see the higher-quality outputs. The Lite fallback is documented in `.env.example` for anyone whose AI Studio project quota can't accommodate a full notebook run — flip `GEMINI_MODEL=gemini-2.5-flash-lite` and the pipeline runs identically with a small quality cost on stylised painted signatures. Stylised signatures like the M in "M.A. Gomez" rendered as three vertical brush strokes can misread on either model; that's a vision-capability limit, not a prompt bug.

Two Gemini-specific configuration choices in `vision_client.py`:

1. **Native JSON mode** via `response_mime_type="application/json"` — eliminates an entire class of "the model returned prose around the JSON" failures.
2. **`thinking_budget=0`** — Gemini 2.5 models burn output tokens on hidden reasoning by default. For deterministic structured-JSON tasks every output token should go to the visible JSON; with thinking on, pass 1 truncated mid-string and pass 2 returned empty arrays. The override is configurable via `GEMINI_DISABLE_THINKING`.

The provider boundary is isolated in `libs/vision_client.py` (single file, ~80 lines). Swapping in Claude, GPT-4o, or a self-hosted vision model is a one-file change — services and prompts stay untouched.

## 2. Architecture — microservices, three containers + Redis

- **gateway** (port 8000): the only public surface. Validates request bodies with Pydantic, routes to the right backend, normalizes error envelopes.
- **artwork** (port 8001): Task 1. Single endpoint `/analyze`.
- **signature** (port 8002): Task 2. Single endpoint `/extract`.
- **redis**: caches vision results keyed by `sha256(normalized image bytes)` so repeated runs (during reviewer evaluation) don't re-bill.
- **SQLite** (mounted volume): a tiny audit log of every analysis. Optional; could be removed without affecting behaviour.

**Why split tasks into separate services rather than one process with two endpoints?**
1. The two pipelines have independent prompt-iteration cycles. Bumping the signature prompt shouldn't redeploy the artwork service.
2. Different latency profiles — Task 2 fans out across N images and benefits from being scaled independently.
3. The brief explicitly asks for microservices.

The shared `libs/` module is the deliberate seam: each service is thin, all real logic (image normalization, vision calls, caching, persistence) is one import away. The signature service could be cloned into a third pipeline (e.g. provenance-label extraction) by reusing the same libs.

## 3. Task 1 prompt — single-pass JSON

`services/artwork/prompts/artwork_v1.md`

- Split into `## SYSTEM` (role and global rules) and `## USER INSTRUCTION` (concrete output contract).
- Rules cover the brief's constraints explicitly: derive from visual content only, ignore frame/watermark/chrome, focus on the primary artwork.
- Caption word limit (≤20) is enforced **twice**: in the prompt, and in the Pydantic schema (`field_validator`) so a non-compliant model response is rejected at the gateway boundary instead of leaking to the client.

## 4. Task 2 prompt — two-pass extract → classify

This is the core prompt-engineering choice in the project.

**Pass 1 — `extract_text_v1.md`**: exhaustively transcribe every text region in the image. The model is told it is *not* deciding what's a signature — only locating and transcribing every candidate (signatures, titles, dates, edition numbers, publisher names, stamps, monograms).

**Pass 2 — `classify_signature_v1.md`**: receives the transcribed regions (as embedded JSON) *and* the original image again, then classifies each as signature or noise. The image is included in pass 2 because visual context (handwriting style, location relative to plate, ink vs paint vs pencil) is decisive — pass 2 cannot rely on text alone.

**Why two-pass over single-pass?**

| concern | single-pass | two-pass |
|---|---|---|
| Noise rejection on hard cases (Hockney, Llorca with title + edition + date all in pencil) | The model often returns the title or the edition number alongside the signature | Pass 1 surfaces them all; pass 2 explicitly rejects each |
| Prompt clarity | One prompt has to do extraction *and* classification, dilutes both | Each prompt has one job |
| Debuggability | Hard to tell whether a wrong output is an extraction miss or a classification miss | Pass 1's region list is inspectable; failures are localizable |
| Cost | 1 vision call per image | 2 vision calls per image |

The 2× cost is acceptable because Redis caches the *final* classified result, so repeat runs are free.

**Confidence calibration**: pass 2 prompt defines bands (0.9-1.0 clear, 0.7-0.9 ambiguous, 0.4-0.7 monogram-only, <0.4 exclude). The model is told to *exclude* anything below 0.4 rather than return a low-confidence signature.

**Negative examples in the prompt**: I name each excluded category with concrete examples from the brief: `La Pythonisse` for plate titles, `147/280` for editions, `1972` for dates, `E.A.` for artist's-proof annotations, `Taschen` for publisher names. Naming the actual failure modes from the brief is the single highest-leverage prompt-engineering move on this task.

## 5. Output structure — Pydantic-enforced JSON

- `ArtworkResult` enforces `keywords` length 5–10, caption ≤20 words, all fields trimmed.
- `Signature` enforces `0.0 ≤ confidence ≤ 1.0`, non-empty text and location.
- The gateway validates request bodies with Pydantic; bad inputs get 422 with a structured error.
- Model outputs that fail schema validation produce a 502 with the underlying validation error — they never silently pass through.

The `_extract_json` helper in `vision_client.py` is tolerant of three failure modes: bare JSON, fenced JSON (` ```json ... ``` `), and JSON embedded in prose. This is defensive but bounded — once a vision call returns malformed JSON repeatedly the operator sees it in the 502 detail.

## 6. Caching strategy

- Key: `weybees:{namespace}:{prompt_version}:{image_sha256}`.
- Including the prompt version in the key means a prompt change automatically invalidates cached results without a manual flush.
- Default TTL 30 days; configurable via `VISION_CACHE_TTL_SECONDS`.
- The image hash is taken on the *normalized* bytes (after resize / re-encode), so the same source image fetched via two different URLs still hits the same cache entry.

## 7. Image handling

`libs/image_loader.py` accepts URL, raw base64, or `data:` URI. It downscales any image whose longest side exceeds 1568px (Anthropic's recommended ceiling for vision inputs) and re-encodes as JPEG q88 if the payload exceeds 5 MB or originated in an alpha-channel format. This keeps token cost predictable.

## 8. What I deliberately left out

- **AuthN/AuthZ** — the brief doesn't ask for it; adding it would dilute the demo.
- **Rate limiting** — Redis is already in the stack, would be one middleware to add. Skipped for scope.
- **Postgres / ORM** — SQLite is enough for an audit log; Postgres would be over-engineering at this size.
- **Streaming responses** — vision calls are short enough that buffered JSON is fine; streaming adds client complexity for no UX win.
- **Multi-model fallback** — could add an Opus retry on schema-validation failure. Skipped; would mask prompt bugs rather than fix them.

## 9. Known limitations & next steps

- The brief references Suduca Lot 242 for the Guy DUC and Llorca lithographs, but the auction house has recycled that URL — it now points at an Yvon GRAC beach scene. The committed `fixtures/` set substitutes Yvon GRAC images (full view, signature close-up, framed view) plus a separate monogram seascape; these exercise the same Task 2 paths. The Hockney and Bonhams reference images from the brief are intact. See `fixtures/README.md`.
- Confidence scores are model-reported, not calibrated against ground truth. With a labelled set we could fit a per-confidence-band precision curve and apply Platt scaling.
- The two-pass approach doubles latency. For a production system I'd consider a hybrid: pass 1 only, with a sharper single-prompt for the common case, falling back to pass 2 when pass 1 returns ≥2 handwritten regions (the ambiguous case).
