"""Headless demo runner: hits the gateway with the full fixture set and
captures every response to submission/outputs.json.

Usage:
    python scripts/run_demo.py

Requires the docker compose stack to be running on http://localhost:8000.
Stdlib only — no pip install needed.
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
    path = FIXTURES / name
    mime = "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def post_json(url: str, payload: dict, timeout: float = 300.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def get_json(url: str, timeout: float = 10.0) -> dict:
    with request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print(f"gateway: {GATEWAY}")
    try:
        health = get_json(f"{GATEWAY}/health")
    except Exception as exc:
        print(f"health check failed: {exc}", file=sys.stderr)
        return 1
    print("health:", json.dumps(health, indent=2))

    outputs: dict = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "gateway_health": health,
        "task1": None,
        "task2": None,
        "errors": [],
    }

    print(f"\n--- Task 1 on {TASK1_IMAGE} ---")
    try:
        t1 = post_json(f"{GATEWAY}/task1/analyze", {"image": as_data_uri(TASK1_IMAGE)})
        outputs["task1"] = {"image": TASK1_IMAGE, "result": t1}
        print(json.dumps(t1, indent=2, ensure_ascii=False))
    except Exception as exc:
        msg = f"task1 failed on {TASK1_IMAGE}: {exc}"
        print(msg, file=sys.stderr)
        outputs["errors"].append(msg)

    print(f"\n--- Task 2 on {len(TASK2_IMAGES)} fixtures ---")
    try:
        t2 = post_json(
            f"{GATEWAY}/task2/extract",
            {"images": [as_data_uri(n) for n in TASK2_IMAGES]},
        )
        for sig in t2.get("signatures", []):
            idx = sig.get("image_index")
            if isinstance(idx, int) and 0 <= idx < len(TASK2_IMAGES):
                sig["image"] = TASK2_IMAGES[idx]
        outputs["task2"] = {"images": TASK2_IMAGES, "result": t2}
        print(json.dumps(t2, indent=2, ensure_ascii=False))
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
