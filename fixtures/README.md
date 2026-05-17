# Reference fixtures

These images are used by `notebook/demo.ipynb` and (optionally) by integration tests when `RUN_VISION_TESTS=1`. They are committed so the demo can run fully offline.

| file | source | what it tests |
|---|---|---|
| `david_hockney_my_window.webp` | Taschen book cover | **Task 2 noise-rejection canary** from the brief. Must return `David Hockney` and exclude title `my Window` and publisher `Taschen`. |
| `winter_in_the_land.jpg` | Bonhams Lot 3030 | **Task 2 clean baseline** from the brief. Single painted signature `M.A. Gomez` lower right, no other text. Also a good Task 1 input. |
| `yvon_grac_beach.jpg` | Suduca CDN | Task 1 + Task 2: full unframed view of an Yvon GRAC beach scene with a painted signature lower-left. |
| `yvon_grac_signature_closeup.jpg` | Suduca CDN | Task 2 close-up of the same signature — tests signature extraction when the artist's mark fills the frame. |
| `yvon_grac_framed.jpg` | Suduca CDN | Task 2 frame-rejection test — gilded frame surrounds the artwork; the frame must be ignored. |
| `seascape_monogram.jpg` | Suduca CDN | Task 2 edge case: a small painted monogram in the corner of a blue seascape — should be returned with lower confidence per the prompt's calibration bands. |

## On the brief's Suduca reference

The brief points at Suduca Lot 242 for Guy DUC's *La Pythonisse* and Marie José LLORCA's *Grange brûlée à Dammartin sous Tigeaux*. That URL was recycled by the auction house and now points at a different artwork (Yvon GRAC). The Yvon GRAC images shipped here exercise the same Task 2 paths — handwritten signature, gilded frame artifacts, signature close-up — so the system can still be evaluated end-to-end. If you find an archived copy of the original Guy DUC / Llorca images, drop them into this directory and they will be picked up by the notebook.

## Regenerating

If a fixture is missing, run:

```bash
python scripts/fetch_fixtures.py
```
