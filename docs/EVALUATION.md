# Evaluation Map

Direct mapping from each evaluation criterion in the Weybees brief to the specific files, behaviours, and outputs that demonstrate it. Intended as a reading guide for a reviewer.

## 1. Accuracy

**Brief:** *"Does Task 1 correctly describe the artwork? Does Task 2 return only the signature and nothing else?"*

| evidence | location |
|---|---|
| Task 1 produces grounded `{keywords, caption, description}` derived purely from visual content | `submission/outputs.json` → `task1.result` |
| Task 2 returns one or more signature entries per image with `signature_text`, `location_hint`, `confidence` | `submission/outputs.json` → `task2.result.signatures` |
| Hockney book cover (the brief's canary): returns `David Hockney`, **excludes** title `my Window` and publisher `Taschen` | same file, `image_index: 0` |
| Bonhams "Winter in the Land" (the brief's clean baseline): returns the painted signature | same file, `image_index: 1` |

**Honest limitations** (documented in `DESIGN.md` §9 and `outputs.json.notes`):

- Stylised painted signatures are misread by Gemini at the OCR layer — `M.A. Gomez` reads as `W.A. GOMEZ`, `Y. Grac` reads as `Eric` / `FPRTC`. The pipeline correctly locates the signature region and excludes non-signature text; the misread is a vision-capability limit, not a prompt or schema bug.

## 2. Noise rejection

**Brief:** *"How well does Task 2 filter out non-signature text (titles, numbers, dates, publisher names, stamps)?"*

This is the criterion the system is most deliberately engineered for.

| evidence | location |
|---|---|
| Two-pass design isolates "find text" from "classify text" so each prompt has one job | `services/signature/main.py` (`_process_image`, `_pass1_extract_regions`, `_pass2_classify`) |
| Pass-2 prompt names the brief's hard cases as explicit negative examples (`La Pythonisse`, `147/280`, `1972`, `E.A.`, `Taschen`) | `services/signature/prompts/classify_signature_v2.md` § "EXCLUDE — these are NEVER signatures" |
| Pass-2 prompt also names the positive Hockney case (artist-name-on-cover-as-signature) — added in v2 after the v1 false negative | same file § "INCLUDE — these ARE signatures" |
| Confidence calibration bands tell the model to *exclude* anything <0.5 rather than over-include | same file § "Confidence calibration" |
| Hockney canary passes end-to-end in the committed output | `submission/outputs.json` `image_index: 0` |

## 3. Output structure

**Brief:** *"Is the output clean, consistent JSON? Are all required fields present and correctly typed?"*

| evidence | location |
|---|---|
| Pydantic schemas at every API boundary | `services/artwork/schemas.py`, `services/signature/schemas.py` |
| `ArtworkResult` enforces 5–10 keywords and the brief's ≤20 word caption rule via `field_validator` | `services/artwork/schemas.py:_trim_keywords`, `:_caption_word_count` |
| `Signature` clamps `confidence` to `[0.0, 1.0]` and strips whitespace from text fields | `services/signature/schemas.py:_strip` |
| Model output that fails schema validation produces `502 Bad Gateway` with the validator's error — never silently passes through | `services/artwork/main.py:analyze`, `services/signature/main.py:_pass1_extract_regions` / `_pass2_classify` |
| Native JSON-mode at the model level (`response_mime_type="application/json"`) eliminates an entire class of "prose around the JSON" failures | `libs/vision_client.py:call_vision` |
| Tolerant JSON extractor as a defence in depth (handles fenced + prose-wrapped output) | `libs/vision_client.py:_extract_json` |
| Auto-generated Swagger UI documents the contracts | `http://localhost:8000/docs` when running |

## 4. Prompt engineering

**Brief:** *"Is the AI prompt well-designed, specific, and reproducible? Is it robust to edge cases?"*

| evidence | location |
|---|---|
| Prompts are **versioned files**, not strings embedded in code | `services/artwork/prompts/artwork_v1.md`, `services/signature/prompts/extract_text_v1.md`, `classify_signature_v2.md` |
| Cache key includes the prompt version, so a bump auto-invalidates without manual flush | `libs/cache.py:make_key` callers |
| Prompts are split into `## SYSTEM` (role + global rules) and `## USER INSTRUCTION` (the concrete output contract) | `services/*/main.py:_load_prompt` / `_split` |
| Two-pass design is itself a prompt-engineering decision — each prompt has one job, both are easier to write and audit | `DESIGN.md` §4 |
| Negative examples in the classifier are drawn from the brief's actual hard cases, not generic | `classify_signature_v2.md` |
| v2 of the classifier was created in response to a real failure (Hockney canary returning empty on v1) rather than guessed | `30eaa31` commit message, `DESIGN.md` §4 |
| Project-scoped Claude Code agent enforces "one variable at a time" prompt iteration discipline | `.claude/agents/prompt-engineer.md` |

## 5. Code quality

**Brief:** *"Is the implementation clean, modular, and easy to extend to other artworks or image sets?"*

| evidence | location |
|---|---|
| Microservices boundary — Task 1 and Task 2 are independent services with their own prompts and schemas | `services/artwork/`, `services/signature/`, `services/gateway/` |
| Shared concerns extracted to libs — `image_loader`, `vision_client`, `cache`, `history` — services are thin routers around these | `libs/` |
| Provider boundary is exactly one file (~80 lines) — swapping Gemini for Claude / GPT-4o is a single-file change | `libs/vision_client.py` |
| Per-image fault tolerance in Task 2: sequential loop with per-image try/except so one quota error doesn't poison the batch | `services/signature/main.py:extract` |
| Pydantic-typed everything — no untyped dicts crossing a service boundary | `services/*/schemas.py` |
| One-line docstring on every function and class | `158bd03` commit; every Python file in the repo |
| Unit tests cover schema contracts, image-loader edge cases, and JSON extraction — all run offline with no API key needed | `tests/` |
| Repo layout is conventional and discoverable | `docs/ARCHITECTURE.md` "Service responsibilities" |

## 6. Justification

**Brief:** *"Can the candidate explain their design choices — model selection, prompt structure, filtering logic?"*

| evidence | location |
|---|---|
| `DESIGN.md` is the primary justification artifact — model selection table with five options scored, architecture rationale, two-pass design choice, caching strategy, deliberate omissions | `DESIGN.md` |
| Commit history reads as a justified evolution (Anthropic → Gemini for free tier, classifier v1 → v2 for the Hockney case, sequential processing for the RPM cap) | `git log --oneline` on the repo |
| Memory of build-time decisions captured in inline comments only where the *why* would surprise a future reader (e.g. `GEMINI_DISABLE_THINKING`) | `libs/vision_client.py` |
| Per-task documentation under `docs/` — Architecture, API, Operations, this Evaluation map | `docs/` |
| Operations guide documents every real error hit during build and the actual fix applied | `docs/OPERATIONS.md` "Common errors" |

## Suggested reading order for a reviewer

1. `README.md` — quickstart and architectural shape.
2. `submission/outputs.json` — what the system actually produced; the `notes` array narrates the run.
3. `DESIGN.md` — justification of every non-obvious choice.
4. `docs/ARCHITECTURE.md` — diagram + request flows + cache key design + two-pass rationale.
5. `services/signature/prompts/classify_signature_v2.md` — the most interesting prompt in the system; demonstrates how the brief's noise-rejection requirement is encoded.
6. `docs/EVALUATION.md` (this file) — to cross-check the criteria.
7. `docs/OPERATIONS.md` — only if you want to run it yourself.
