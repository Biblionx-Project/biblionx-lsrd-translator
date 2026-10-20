# Sign images

The sign illustrations served by the API (`rutas_imagenes.ruta_imagen` =
`extracted_images/lsrd_XXXX.png`) are **not stored in git**. `extracted_images/` is gitignored and
lives on local disk (or wherever `BIBLIONX_IMAGES_DIR` points). Without it, translation still
works and clients show a text card.

## Regenerating images from the official PDF

The original extraction cropped a fixed region per entry, and for about half of the entries
(1,228 of 2,476) that region held dictionary text (headword, definition fragments) instead of
the drawing. Those images were regenerated with:

```bash
uv run tools/recrop_sign_images.py --pdf <official dictionary PDF> \
    --backup <folder outside the repo> --bad-from bad_ids.json
# or: --ids lsrd_0001 lsrd_1248 ...   |   --all
# --dry-run <dir> writes to <dir> instead of extracted_images/
# --qa-only only scores the current images (no PDF needed)
```

For each entry the tool reads its page (`palabras.pagina`) with pdfminer.six, finds the entry's
headword in the page grid (the same page model as `tools/recover_dictionary_entries.py`), takes
the illustration on the free side of that grid cell, renders it with pypdfium2 at 144 dpi
(scale 2, the resolution of the existing crops), trims white margins, grid rules and the
running page title, and writes `extracted_images/<id>.png`. Rows that the original extraction
split into pieces (`BATERÍA` / `(INSTRUMENTO` / `MUSICAL)`) are matched by joining neighbouring
rows of the same page. Letter section dividers (`B` on page 67, `C` on page 84, ...) reuse the
fingerspelling sign printed on the next page. Database rows, ids and image paths are never
modified. Before overwriting, the current folder is copied once to `--backup` (required unless
`--dry-run` or `--no-backup`; an existing backup is never overwritten).

Dependencies (declared inline, PEP 723): `pdfminer.six`, `pypdfium2`. PNG encoding and decoding
use the standard library only.

## QA rule

Every LSRD illustration shows a person signing, drawn with flat skin-tone hands and face. An
image is accepted when at least **0.5 %** of its sampled pixels (every 3rd pixel of every 3rd
row) match the skin rule `R > 170, G > 120, B > 80, R - B > 35, R > G > B, R - G < 70`.
Real illustrations score about 0.05 to 0.25; text-only crops score 0.0.

The tool scores every image it writes and reports any below the threshold.
`tests/test_image_quality.py` applies the same rule to every `lsrd_*.png` referenced by the
database (skipped when `extracted_images/` is absent, e.g. in CI). Entries whose illustration
genuinely lacks skin tones would go in that test's documented `ALLOWLIST`; it is currently empty.

## Other files in extracted_images/

20 files named like `0050_01_amplio_plia.png` (pages 50 to 52, AMPLIO to AÑO) are leftovers of an
early extraction prototype (`<page>_<n>_<word>.png`). No database row references them; the same
entries use `lsrd_0143` to `lsrd_0162`. They can be ignored.
