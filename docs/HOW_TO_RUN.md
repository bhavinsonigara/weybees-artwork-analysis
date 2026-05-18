# How to Run

Step-by-step from zero to a working demo. ~5 minutes if you have Docker and a Gemini key, ~10 minutes including the install of those.

## 1. Prerequisites

You need two things on your machine:

**Docker Desktop** — https://www.docker.com/products/docker-desktop/
After install, open Docker Desktop and wait for the whale icon to go solid. Then verify in a terminal:

```bash
docker --version
docker compose version
```

**A free Gemini API key** — https://aistudio.google.com/app/apikey
Sign in with any Google account (no payment method required). Click "Create API key" → "Create API key in new project". Copy the key (starts with `AIza...`).

## 2. Get the code

```bash
git clone https://github.com/bhavinsonigara/weybees-artwork-analysis.git
cd weybees-artwork-analysis
```

## 3. Create your `.env`

```bash
cp .env.example .env
```

Open `.env` in any editor and replace the placeholder on the first line with the key you just created:

```
GEMINI_API_KEY=AIza...your-real-key-here...
```

Save the file. (`.env` is gitignored — your key stays local.)

## 4. Start the stack

```bash
docker compose up --build
```

First run takes 1–3 minutes (downloads Python image, installs requirements, builds three service images, starts Redis). Subsequent runs are seconds.

When it stops printing lines and just hangs with both services on `Application startup complete`, you're up.

If you'd rather run it in the background:

```bash
docker compose up -d --build
```

## 5. Verify health

In a separate terminal:

```bash
curl http://localhost:8000/health
```

Expect a JSON body like:

```json
{
  "gateway": "ok",
  "artwork":   { "status": "ok", "prompt_version": "artwork_v1" },
  "signature": { "status": "ok", "extract_prompt": "extract_text_v1",
                                 "classify_prompt": "classify_signature_v2" }
}
```

If you see this, everything is wired up.

## 6. Hit the endpoints

### Task 1 — analyse one artwork

```bash
curl -X POST http://localhost:8000/task1/analyze \
  -H "Content-Type: application/json" \
  -d '{"image":"https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg&height=1500&quality=90"}'
```

Returns `{keywords, caption, description}` for the image.

### Task 2 — extract signatures from one or more images

```bash
curl -X POST http://localhost:8000/task2/extract \
  -H "Content-Type: application/json" \
  -d '{
        "images": [
          "https://upload.wikimedia.org/wikipedia/en/2/2d/David_Hockney_My_Window.jpg"
        ]
      }'
```

Returns `{signatures: [...]}`. For the Hockney image you should see `David Hockney` returned with title `my Window` and publisher `Taschen` excluded — that's the brief's noise-rejection canary passing.

## 7. Run the full demo against every committed fixture

The repo ships with six reference images under `fixtures/` so you can exercise the whole pipeline without depending on any external URL:

```bash
python scripts/run_demo.py
```

Stdlib only — no pip install needed on the host. The script hits the gateway with Task 1 on one fixture + Task 2 on all six, and writes everything (model tags + notes + per-image errors) to `submission/outputs.json`.

You can already see what that file looks like at `submission/outputs.json` in the repo — it's the artifact from the most recent demo run.

## 8. Stop the stack

```bash
docker compose down               # stops + removes containers
docker compose down -v            # also wipes the Redis cache volume
```

The SQLite audit log at `./data/history.sqlite3` persists across runs by design.

---

## When things go wrong

| symptom | most likely cause | what to do |
|---|---|---|
| Health check fails after `docker compose up` | image build failed | scroll the `docker compose up` output for the actual error |
| `429 RESOURCE_EXHAUSTED ... limit: 0` | your AI Studio project has no free-tier quota on the configured model | switch to a different model in `.env` (`GEMINI_MODEL=gemini-2.5-flash-lite`), then `docker compose up -d --force-recreate` |
| `429 ... GenerateRequestsPerDayPerProjectPerModel-FreeTier` | hit the daily request cap | wait until the UTC day rolls over, or switch model (each model has its own daily counter) |
| Containers running but `.env` changes don't take effect | `restart` doesn't re-read `env_file` | `docker compose up -d --force-recreate` |

For the full troubleshooting catalogue see [OPERATIONS.md](OPERATIONS.md).

## Where to look next

- **What the system actually produced**: [`submission/outputs.json`](../submission/outputs.json)
- **Why each design choice**: [`DESIGN.md`](../DESIGN.md)
- **Endpoint reference**: [`API.md`](API.md)
- **Architecture deep-dive**: [`ARCHITECTURE.md`](ARCHITECTURE.md)
