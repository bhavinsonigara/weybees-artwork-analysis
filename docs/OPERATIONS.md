# Operations Guide

How to run, observe, and recover this stack. Every error documented here was hit at least once during build — the solutions are real, not speculative.

## Prerequisites

- **Docker Desktop** (Linux backend via WSL 2 on Windows). Test with `docker --version` and `docker compose version`.
- **A Gemini API key** from Google AI Studio (https://aistudio.google.com/app/apikey) — free, no payment method required.

The host machine doesn't need Python, pip, jupyter, or any of the project's runtime dependencies — everything lives inside the containers.

## Bring up the stack

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY=AIza...

docker compose up --build         # foreground
docker compose up -d --build      # detached
```

First build pulls Python 3.11, installs the requirements, and creates three images (`weybeestask-gateway`, `-artwork`, `-signature`) plus the Redis container. Takes 1–3 minutes on a warm Docker cache, longer cold.

Verify everything is reachable:

```bash
curl http://localhost:8000/health
```

Expect a JSON body with `gateway: ok` and both backends reporting their prompt versions.

## Tear down

```bash
docker compose down              # stops + removes containers, keeps volumes
docker compose down -v           # also removes the Redis volume (cache flush)
```

The SQLite history lives in `./data/` on the host and persists across `down`/`up` cycles. Delete it manually if you want a clean slate.

## Environment variables

| var | default | purpose |
|---|---|---|
| `GEMINI_API_KEY` | — *required* | Your AI Studio key. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model id. See "Picking a model" below. |
| `GEMINI_MAX_TOKENS` | `4096` | Output cap per vision call. |
| `GEMINI_DISABLE_THINKING` | `1` | Set to `0` to re-enable Gemini 2.5's hidden reasoning tokens (not recommended for our structured-JSON tasks — see "JSON truncation" below). |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string. Inside Docker leave as is. |
| `SQLITE_PATH` | `/app/data/history.sqlite3` | Audit log path inside the container; mapped to `./data/history.sqlite3` on the host. |
| `ARTWORK_SERVICE_URL` | `http://artwork:8001` | Where the gateway forwards Task 1. |
| `SIGNATURE_SERVICE_URL` | `http://signature:8002` | Where the gateway forwards Task 2. |
| `VISION_CACHE_TTL_SECONDS` | `2592000` (30 days) | How long cached vision results live. |
| `LOG_LEVEL` | `INFO` | Standard `logging` levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

After editing `.env`, re-create the containers so the new values are read:

```bash
docker compose up -d --force-recreate
```

(`restart` alone does **not** re-read `env_file`.)

## Logs

```bash
docker compose logs -f                  # follow all services
docker compose logs --tail 80 signature # last 80 lines of one service
```

The vision client logs every call as:

```
vision_call model=gemini-2.5-flash input_tokens=728 output_tokens=124
```

Useful for cost tracking and confirming which model was actually used per call.

## Cache inspection

```bash
docker compose exec redis redis-cli KEYS 'weybees:*'
docker compose exec redis redis-cli GET 'weybees:signature:extract_text_v1:classify_signature_v2:<sha>'
docker compose exec redis redis-cli DEL  'weybees:signature:extract_text_v1:classify_signature_v2:<sha>'
docker compose exec redis redis-cli FLUSHALL    # nuclear option
```

Key pattern: `weybees:{namespace}:{prompt_versions...}:{image_sha256}`. A prompt-file change bumps the version, so old keys naturally fall out of use without a flush.

## SQLite audit log

```bash
docker compose exec artwork python -c "
import sqlite3
for row in sqlite3.connect('/app/data/history.sqlite3').execute(
    'SELECT id, created_at, task, substr(image_sha,1,12), length(result_json) FROM analyses ORDER BY id DESC LIMIT 20'
):
    print(row)
"
```

Or open `./data/history.sqlite3` directly on the host with any SQLite client.

## Running the demo headlessly

```bash
python scripts/run_demo.py
```

Stdlib only, no pip install needed. Hits Task 1 on one fixture + Task 2 on all six fixtures, captures everything to `submission/outputs.json` with per-entry model tags. Re-running preserves model tags from prior runs (for cache hits) and tags new results with whatever `GEMINI_MODEL` currently names.

## Picking a model

| model | RPD (free tier on new project) | quality | when |
|---|---|---|---|
| `gemini-2.5-flash` | ~20 | best on this task | demo runs, final submission |
| `gemini-2.5-flash-lite` | much higher | weaker stylised-handwriting OCR, noise rejection still works | iterating prompts, hitting daily flash cap |
| `gemini-2.0-flash` | often 0 on new projects | strong | only if your project has free-tier access (check ai.dev/rate-limit) |

Swap by editing `GEMINI_MODEL` in `.env` and recreating containers. The provider boundary is in `libs/vision_client.py` (~80 lines) — to use a different provider entirely, that's the only file to rewrite.

## Common errors (with real causes and fixes)

### `429 RESOURCE_EXHAUSTED ... limit: 0, model: gemini-2.0-flash`

Your AI Studio project doesn't have free-tier access to that model — quota is literally zero, not "exceeded." Common on brand-new projects.

**Fix**: switch to a model that does (`gemini-2.5-flash` usually has free-tier access). Check `https://ai.dev/rate-limit` for the per-model RPD you actually have.

### `429 RESOURCE_EXHAUSTED ... GenerateRequestsPerMinutePerProjectPerModel-FreeTier`

You're firing more than the per-minute cap (5 RPM on flash free tier). The Gemini SDK retries with the suggested 40–50s backoff automatically.

**Fix**: nothing immediate — wait. The signature service already processes images sequentially to keep concurrency low, and per-image try/except means a final 429 doesn't kill the batch. Long-term, lower batch size or wait longer between submissions.

### `429 ... GenerateRequestsPerDayPerProjectPerModel-FreeTier`

You've hit the daily cap (20 RPD on flash for new projects). Resets at the start of the UTC day on Google's clock.

**Fix**: switch to `gemini-2.5-flash-lite` in `.env` (separate daily counter). The demo runner preserves model tags from previous runs, so a mixed-model output is still legible.

### `502 Bad Gateway` from `/task2/extract`

The signature service returned an error. Always check its logs first:

```bash
docker compose logs --tail 60 signature
```

Three usual root causes:

1. **Quota / 429 chain** (see above) — visible as `google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED`.
2. **Schema validation failure** on the model's output — visible as `pass1 invalid output` or `schema validation failed`. Inspect the raw model text printed in the log line. Usually a prompt iteration problem.
3. **(Historical) sqlite deadlock** — fixed in `libs/history.py` by initialising the schema at import time. If you see hangs with no log output, you're probably regressed.

### Gateway times out before the signature service responds

Symptom: 502 with `upstream unreachable: ReadTimeout`. Cause: with two vision calls per image and back-to-back 429 retries each waiting ~40s, the total can exceed the gateway's HTTPX timeout.

**Fix**: gateway timeout is set to 600s (`services/gateway/main.py`). If you still hit it, the underlying issue is quota — let it cool down before retrying.

### JSON truncation in pass 1 output

Symptom: `Expecting ',' delimiter: line X column Y` parsing the model's pass-1 response, with output cut mid-string. Cause: Gemini 2.5 spends output tokens on hidden "thinking" before emitting the visible response. With thinking on, even small outputs can exhaust `max_output_tokens`.

**Fix**: `GEMINI_DISABLE_THINKING=1` (the default). If you set it to `0`, also raise `GEMINI_MAX_TOKENS` substantially (8192+).

### Empty signature list on a known-good image

Symptom: pass 1 logged plenty of tokens but pass 2 returned `{"signatures": []}`. Cause: pass 2 over-rejecting (was the original problem on the Hockney book-cover canary before classifier v2).

**Fix**: iterate the classifier prompt. Don't relax the schema. See `services/signature/prompts/classify_signature_v2.md` for the convention.

### `.env` first variable not loaded inside containers

Symptom: env vars set in `.env` aren't visible to the running container; only the first variable looks wrong. Cause (Windows specifically): `.env` was written as UTF-8-with-BOM. Docker Compose's env parser treats the BOM as part of the first variable's name.

**Fix**: rewrite the file as UTF-8 without BOM. From PowerShell:

```powershell
$content = Get-Content -Raw -Path .env
[System.IO.File]::WriteAllText('.env', $content, [System.Text.UTF8Encoding]::new($false))
```

## Production considerations (not in scope)

The brief is a demo, so these were deliberately skipped:

- AuthN/AuthZ on the gateway
- Per-tenant rate limiting (Redis is already there, would be one middleware)
- Streaming responses
- Multi-region deployment
- Postgres instead of SQLite once history grows
- Per-call retry / circuit breaker beyond the SDK's defaults
- Tracing / metrics export (Prometheus, OTel)

See `DESIGN.md` §8 for the deliberate-omissions list.
