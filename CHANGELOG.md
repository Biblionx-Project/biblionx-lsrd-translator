# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.2.0] - 2026-10-20

Dictionary recovery, honest metrics, one version source and a CI that runs every test.

### Added
- Dominican lexicon enhancements, question-sign indexing in the engine and a manual extension test page served at `/app/test_page.html`.
- 18 dictionary entries that were printed in the official PDF but missing from the database
  (`lsrd_2459` to `lsrd_2476`: DICCIONARIO, GRANDE, GRANIZO, GRAPA, GRAPADORA, GRAPAR, GRITAR, GROSERO, RA, GRÚA,
  GUANDUL, GUANTE, GUANTE (DEPORTE), GUERRA, GUIAR, GUINEO, LOCRIO DE POLLO, MANGA CORTA, MANGA LARGA), with
  `tools/recover_dictionary_entries.py`, `tools/find_dictionary_gaps.py` and `docs/DICTIONARY_GAPS.md`.
- 24 curated synonym mappings marked `curated-pending-review` (interpreter review pending).
- Evaluation metrics: per-method counts, share and confidence, lemma precision, order accuracy, per-tag breakdown,
  fingerspelling rate, OOV list and latency p50/p95/max. Corpus gains `allowed_lemmas` and `expected_order`.
- `check_metrics.py` flags `--min-precision`, `--max-fingerspelling-rate`, `--min-order-accuracy`, `--max-p95-ms`.
- `VERSION` file as the single version source and `scripts/check_version.py` (exit 1 on mismatch), run in CI and tests.
- Committed 1x1 fixture image under `tests/fixtures/images/` so the image-serving test always runs.
- CI: Python 3.14 in the matrix, version check, full metrics gate, concurrency cancellation.

### Changed
- Browser extension (Manifest V3): accessibility improvements.
- The project was rebranded to Biblionx; VLibras is kept only as a fork note.
- `evaluate.py` now keeps morphology and phrase provenance per token instead of reporting everything as `exact`.
- Lexical coverage 0.8795 to 0.9070; fingerspelled tokens 57 to 44; gold lemma recall stays 0.9747.
- The server, the extension manifest and the OpenAPI spec now all report the same version.

### Fixed
- The image test was silently skipped in CI because `extracted_images/` is not tracked.
- About half of the local sign images (1,228 of 2,458) were crops of dictionary text instead of the sign illustration,
  a systematic error of the original extraction. `tools/recrop_sign_images.py` regenerates every image from the official
  PDF (pdfminer.six + pypdfium2) with a skin-tone QA check; `tests/test_image_quality.py` guards it and
  `docs/IMAGES.md` documents the process. Images remain outside git.
- Browser extension: a triple click (several `mouseup` events) created duplicate overlay hosts, leaving orphaned
  floating buttons on the page; host creation is now shared by concurrent callers.
- Browser extension: the floating button label no longer wraps onto two lines.
- Browser extension: sign images stayed blank on HTTPS pages because a direct `http://127.0.0.1` image is blocked as
  mixed content; images are now fetched by the service worker (only `/extracted_images/` on the configured API origin)
  and passed to the player as `data:` URLs, with the text card as fallback.
- `/app/test_page.html` rendered unstyled under the `/app/` CSP; its styles now live in `test_page.css`, and the
  duplicate copy at the repository root was removed.
- Browser extension: deterministic matches (morphology, phrases) were badged as "AI"; badges now name the actual
  method (approximate match, AI match, synonym) and only appear for non-exact lookups.

## [2.1.0] - 2026-10-04

Production hardening.

### Added
- Continuous integration (GitHub Actions): unit tests on Python 3.12 and 3.13, evaluation quality gate
  (`scripts/check_metrics.py`), `node --check` on extension and web JavaScript, and a secret-pattern scan.
- `scripts/load_test.py`: stdlib load tester reporting p50/p95/p99 latency, errors and HTTP 429 count.
- OpenAPI 3.1 specification in `docs/openapi.yaml`.
- Per-client rate limiting (`BIBLIONX_RATE_PER_MIN`) with HTTP 429 and `Retry-After`.
- `/api/v1/metrics` counters, request ids, and `image_available` on every sign.
- Optional per-client AI rate limit (`BIBLIONX_LLM_RATE_PER_MIN`, off by default; 30 recommended in production).

### Changed
- Sign images are no longer tracked in git. They were only extraction artifacts used to build the database;
  the server reads them from `BIBLIONX_IMAGES_DIR` and, when a file is missing, responses and UIs fall back to a
  text card (word and movement description).
- `backend_api/` no longer holds copies of the engine, data or database; it imports the repository root.
  `scripts/sync_backend.py` was removed.
- AI fallback has no default call cap (`BIBLIONX_LLM_MAX_CALLS=0` means unlimited) so demos can translate broadly.
- CORS is same-origin by default; `BIBLIONX_CORS_ORIGIN` opts in to specific origins or `*`.

## [2.0.0] - 2026-10-04

ML/NLP translation layer and UI refresh.

### Added
- Dominican Spanish normalization, phrase segmentation, morphology and LSRD grammar rules.
- Curated synonyms, character n-gram fuzzy matcher and an optional, cached, env-configured LLM fallback (off by default).
- `match_method` and `confidence` on every sign.
- `/api/v1/health` endpoint and a web playground served at `/app/`.
- Browser extension v2: Shadow DOM player, context menu and settings popup.
- Unit tests, evaluation corpus and `scripts/evaluate.py`.

### Changed
- Hardened threaded API server (body and text limits, safe path handling).
- Lexical coverage improved from 0.689 to 0.880 and gold lemma recall from 0.797 to 0.975.

## [1.0.0]

- Initial LSRD translation engine, SQLite dictionary, REST API, browser extension and English-translated docs.

[2.2.0]: https://github.com/Biblionx-Project/biblionx-lsrd-translator/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/Biblionx-Project/biblionx-lsrd-translator/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Biblionx-Project/biblionx-lsrd-translator/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Biblionx-Project/biblionx-lsrd-translator/releases/tag/v1.0.0
