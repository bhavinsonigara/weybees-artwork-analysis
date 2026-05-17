"""Download reference images used by tests and the demo notebook.

Run once before running tests offline:
    python scripts/fetch_fixtures.py

NOTE on the brief's reference URLs:
- Suduca Lot 242 (https://www.suduca.com/vente/tableaux-estampes-lot-242-2/) was
  recycled by the auction house and no longer points to the Guy DUC / Llorca
  lithographs cited in the brief. As a substitute we ship four images of a
  different Suduca lot (Yvon GRAC, "La petite crique aux mouettes") plus a
  second seascape with a monogram signature. These exercise the same Task 2
  noise-rejection paths (handwritten signature, gilded frame, signature
  close-up, hard-to-read monogram).
- David Hockney "My Window" (Taschen book cover) and Marco Antonio Gomez
  "Winter in the Land" (Bonhams) are sourced as the brief intends.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

FIXTURES = {
    "david_hockney_my_window.webp": "https://taschen.makaira.media/taschen/image/upload/f_webp,w_1200/v1673610310/products-live/9573c6ba25c925247096b97703ae13f9.jpg",
    "winter_in_the_land.jpg":       "https://img2.bonhams.com/image?src=Images%2Flive%2F2014-02%2F26%2F8933227-1-1.jpg&height=1500&quality=90",
    "yvon_grac_beach.jpg":          "https://www.suduca.com/wp-content/uploads/2026/03/1633174296.jpg",
    "yvon_grac_signature_closeup.jpg": "https://www.suduca.com/wp-content/uploads/2026/03/1633174296-1.jpg",
    "yvon_grac_framed.jpg":         "https://www.suduca.com/wp-content/uploads/2026/03/1633174296-2.jpg",
    "seascape_monogram.jpg":        "https://www.suduca.com/wp-content/uploads/2026/03/1633174296-3.jpg",
}

OUT = Path(__file__).resolve().parent.parent / "fixtures"


def main() -> int:
    """Download every fixture in FIXTURES into ./fixtures/, skipping ones already present."""
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "WeybeesFixtureFetcher/1.0"}) as client:
        for name, url in FIXTURES.items():
            target = OUT / name
            if target.exists():
                print(f"skip {name} (exists)")
                continue
            print(f"GET {url}")
            try:
                r = client.get(url)
                r.raise_for_status()
                target.write_bytes(r.content)
                print(f"  -> wrote {name} ({len(r.content)} bytes)")
            except Exception as exc:
                print(f"  ! failed {name}: {exc}")
                failed += 1
    if failed:
        print(f"\n{failed} fixture(s) failed to download. You may need to download them manually.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
