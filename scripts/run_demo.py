"""Headless demo runner: hits the gateway with the full fixture set and
captures every response to submission/outputs.json.

Usage:
    python scripts/run_demo.py

Requires the docker compose stack to be running on http://localhost:8000.
Stdlib only — no pip install needed.

Mixed-model runs:
    When the same fixture set is processed across multiple model swaps
    (e.g. gemini-2.5-flash for the first 3 images, gemini-2.5-flash-lite
    for the rest after hitting the daily quota), each signature entry
    gets a `model` field. If a previous outputs.json already tagged an
    entry with a model, that tag is preserved (Redis cache hits return
    identical text so they are recognised). New entries are tagged with
    whatever model `.env` currently names.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

GATEWAY = "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
ENV_FILE = ROOT / ".env"
OUT = ROOT / "submission" / "outputs.json"

TASK1_IMAGE = "yvon_grac_beach.jpg"
TASK2_IMAGES = [
    "david_hockney_my_window.webp",
    "winter_in_the_land.jpg",
    "yvon_grac_beach.jpg",
    "yvon_grac_signature_closeup.jpg",
    "yvon_grac_framed.jpg",
    "seascape_monogram.jpg",
]


def as_data_uri(name: str) -> str:
    """Read a fixture file and return it as a base64 `data:<mime>;base64,...` URI."""
    path = FIXTURES / name
    mime = "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def post_json(url: str, payload: dict, timeout: float = 600.0) -> dict:
    """POST a JSON payload and return the decoded JSON response (or raise on HTTP error)."""
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def get_json(url: str, timeout: float = 10.0) -> dict:
    """GET a URL and return the decoded JSON response."""
    with request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def env_model() -> str:
    """Read GEMINI_MODEL from .env so each result can be tagged with the active model."""
    if not ENV_FILE.exists():
        return "unknown"
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_MODEL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "unknown"


def load_previous() -> tuple[dict, dict]:
    """Index the previous outputs.json so per-entry `model` tags are preserved across runs."""
    if not OUT.exists():
        return {}, {}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    prev_t1: dict = {}
    if data.get("task1"):
        prev_t1[data["task1"].get("image")] = data["task1"]
    prev_sigs: dict = {}
    for sig in (data.get("task2", {}).get("result", {}).get("signatures", []) or []):
        key = (sig.get("image_index"), sig.get("signature_text"))
        prev_sigs[key] = sig
    return prev_t1, prev_sigs


def main() -> int:
    """Run Task 1 and Task 2 against the fixture set and write outputs.json."""
    current_model = env_model()
    print(f"gateway: {GATEWAY}")
    print(f"current GEMINI_MODEL (from .env): {current_model}")

    try:
        health = get_json(f"{GATEWAY}/health")
    except Exception as exc:
        print(f"health check failed: {exc}", file=sys.stderr)
        return 1
    print("health:", json.dumps(health, indent=2))

    prev_t1, prev_sigs = load_previous()
    outputs: dict = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "gateway_health": health,
        "task1": None,
        "task2": None,
        "errors": [],
    }

    print(f"\n--- Task 1 on {TASK1_IMAGE} (current model: {current_model}) ---")
    try:
        t1 = post_json(f"{GATEWAY}/task1/analyze", {"image": as_data_uri(TASK1_IMAGE)})
        prev = prev_t1.get(TASK1_IMAGE)
        model = (prev or {}).get("model") if prev and prev.get("result") == t1 else current_model
        outputs["task1"] = {"image": TASK1_IMAGE, "model": model, "result": t1}
        print(json.dumps(t1, indent=2, ensure_ascii=False))
    except Exception as exc:
        msg = f"task1 failed on {TASK1_IMAGE}: {exc}"
        print(msg, file=sys.stderr)
        outputs["errors"].append(msg)

    print(f"\n--- Task 2 on {len(TASK2_IMAGES)} fixtures (current model: {current_model}) ---")
    try:
        t2 = post_json(
            f"{GATEWAY}/task2/extract",
            {"images": [as_data_uri(n) for n in TASK2_IMAGES]},
        )
        enriched = []
        seen_indexes: set[int] = set()
        for sig in t2.get("signatures", []):
            idx = sig.get("image_index")
            if isinstance(idx, int) and 0 <= idx < len(TASK2_IMAGES):
                sig["image"] = TASK2_IMAGES[idx]
                seen_indexes.add(idx)
            prev = prev_sigs.get((idx, sig.get("signature_text")))
            sig["model"] = prev.get("model") if prev and "model" in prev else current_model
            enriched.append(sig)
        outputs["task2"] = {
            "images": TASK2_IMAGES,
            "result": {"signatures": enriched},
        }
        missing = [i for i in range(len(TASK2_IMAGES)) if i not in seen_indexes]
        for i in missing:
            outputs["errors"].append(
                {
                    "task": "task2",
                    "image_index": i,
                    "image": TASK2_IMAGES[i],
                    "cause": "no signatures returned (model produced empty list or per-image error in signature service)",
                }
            )
        print(json.dumps(outputs["task2"]["result"], indent=2, ensure_ascii=False))
    except Exception as exc:
        msg = f"task2 failed: {exc}"
        print(msg, file=sys.stderr)
        outputs["errors"].append(msg)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(outputs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT}")

    return 0 if not outputs["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
