# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

