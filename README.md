# Biblionx LSRD Translator

Biblionx translates Spanish text, including Dominican Spanish, into **Dominican Sign Language (Lengua de Señas Dominicana, LSRD)** sign sequences. It ships a Python translation engine (standard library only), a REST API, a web playground and a browser extension.

> The translation input is Spanish (Dominican Republic) and the output is LSRD. Documentation, code and comments are in English; dictionary data and sign descriptions stay in Spanish because they are primary-source data from the official LSRD dictionary.

## What is in this repository

The repository root is the single source of truth for the engine; `backend_api/` imports it instead of keeping copies.

| Path | Description |
| :--- | :--- |
| `lsrd_dictionary.db` | SQLite database: 2,458 lemmas, categories, movement descriptions, image paths. Read-only data. |
| `main.py` | Interactive console translator. |
| `nlp_engine.py` | Text pipeline: normalization, phrases, morphology, grammar. |
| `translator.py` | Lookup chain from tokens to signs, with provenance and confidence. |
| `dominican_lexicon.py`, `phrases.py`, `morphology.py`, `grammar.py` | Pipeline stages. |
| `ml_matcher.py` | Pure Python fuzzy matcher (character n-gram TF-IDF). |
| `llm_fallback.py` | Optional, off-by-default AI fallback. |
| `data/` | `dominican_lexicon.json` and curated `synonyms_extra.json`. |
| `backend_api/` | `server.py` (HTTP API) and `web/` (playground). Imports the engine and database from the repository root. |
| `browser_extension/` | Manifest V3 extension (v2.1). |
| `scripts/` | `evaluate.py` (metrics), `check_metrics.py` (quality gate), `load_test.py` (load tester). |
| `tools/` | `suggest_synonyms.py`, `export_review_sheets.py`, `find_dictionary_gaps.py`, `make_icons.py`. |
| `tests/` | Unit tests and the evaluation corpus. |
| `Dockerfile`, `deploy/` | Container image, Docker Compose and Caddy (HTTPS) configuration. |
| `.github/workflows/ci.yml` | Continuous integration. |
| `docs/` | `ARCHITECTURE.md`, `DEPLOYMENT.md`, `PRIVACY.md`, `STORE_LISTING.md`, `DICTIONARY_GAPS.md`, `openapi.yaml`, `validation/`. |
| `CHANGELOG.md` | Release notes. |

### Sign images are not distributed

The 2,458 sign PNGs (`extracted_images/`) were extraction artifacts used to build `lsrd_dictionary.db`. They are **not stored in the git repository** and the folder is gitignored. To show images, keep them on local disk (default `<repo root>/extracted_images`) or point the server at another folder with `BIBLIONX_IMAGES_DIR`. When an image file is missing, translation still works: each sign gets `"image_available": false` and no `url_imagen`, and the web playground and browser extension show a text card with the word and its Spanish movement description instead of a broken image.

## Translation pipeline

1. **Dominican normalization**: orthographic variants and Dominicanisms are rewritten to standard Spanish before analysis (for example `pa'` to `para`), only when a sign exists for the standard word.
2. **Phrase segmentation**: multi-word dictionary entries such as `buenos dias` are merged and signed as one unit (greedy longest match).
3. **Morphology**: a conservative lemmatizer maps conjugations, plurals, gender and diminutives to words that actually exist in the dictionary.
4. **LSRD grammar**: clause-level reordering (time first, negation last, question words last).
5. **Lookup chain**: exact entry, dictionary synonyms, curated synonyms, ML fuzzy match, optional AI choice, then A-Z fingerspelling.

Every returned sign carries `match_method` and `confidence`. See `docs/ARCHITECTURE.md`.

### ML fuzzy matching

Unknown words are compared with the dictionary using character n-gram TF-IDF vectors, an inverted index, and a Damerau-Levenshtein rerank. Short words and protected words never fuzzy-match. It runs locally with no network access.

### Optional AI fallback (off by default)

When fuzzy matching is not confident, an LLM can pick among a short list of dictionary candidates. It is disabled unless you opt in, and it is built to be cheap:

- It only chooses an index among candidates (tiny output), never generates text.
- Results, including negative ones, are cached on disk (`data/.llm_cache.json`, never committed).
- No call cap by default (`BIBLIONX_LLM_MAX_CALLS=0` means unlimited) so a demo can translate broadly. A positive value still caps calls per process.
- Optional process-wide rate limit `BIBLIONX_LLM_RATE_PER_MIN` (off by default). Cached answers never count against either limit.
- Any error falls back to fingerspelling.

**Cost recommendation.** For a public demo, set `BIBLIONX_LLM_RATE_PER_MIN=30` and a monthly spend limit in the provider console. On Claude Haiku 4.5 an uncached lookup costs about $0.0003 (roughly 250 input and 8 output tokens at $1/$5 per million tokens), so the cache keeps real spend very low.

Configure it only through environment variables; see `.env.example`. **Never commit API keys or a real `.env` file.** Keys are read from the environment and are never logged or written to disk.

## Quick start

Python 3 and the standard library are enough; no `pip install`.

```bash
python main.py                          # interactive console
python backend_api/server.py             # API + web playground
```

Then open `http://127.0.0.1:8000/app/`.

### Web playground (`/app/`)

A responsive, accessible UI with light and dark themes: type or pick an example sentence, see the gloss timeline, play the sign sequence with previous/next/speed controls, and inspect each sign's description, dictionary page and match confidence.

### API

- `POST /api/v1/translate` with `{"texto": "..."}` returns the analysis and `secuencia_senas`.
- `GET /api/v1/words/{lemma}` direct dictionary lookup.
- `GET /api/v1/health` health check.
- `GET /api/v1/metrics` request counters (enabled by default only on localhost; see `BIBLIONX_METRICS`).
- `GET /app/` web playground; `GET /extracted_images/{id}.png` sign images, served from `BIBLIONX_IMAGES_DIR` when present.

The full contract is in `docs/openapi.yaml`. Each sign includes `image_available`; `url_imagen` is omitted when the file is missing.

### Security features

- Per-client rate limiting on translate and word lookups (`BIBLIONX_RATE_PER_MIN`, default 120 per minute), answering HTTP 429 with `Retry-After`.
- CORS is same-origin only by default; `BIBLIONX_CORS_ORIGIN` opts in to a comma-separated list of origins or `*`.
- Security headers on every response and a strict Content-Security-Policy on `/app/` (no inline code, no third-party fonts).
- Structured JSON request logs with a hashed client identifier and request id; the submitted text is never logged.
- `BIBLIONX_TRUST_PROXY=1` takes the client IP from `X-Forwarded-For` (use only behind a trusted reverse proxy).
- Secrets are read from the environment only; CI scans for key patterns.

### Deployment

See `docs/DEPLOYMENT.md` for local run, Docker, and Docker Compose with automatic HTTPS (Caddy). In containers, mount the images folder read-only at `/data/images`.

### Browser extension (v2.1)

Load `browser_extension/` as an unpacked extension (`chrome://extensions`, Developer Mode). Select text on any page and use the floating button or the "Translate to LSRD" context menu to open the sign player overlay. v2 adds adjustable playback speed, a settings popup (API base URL and default speed, kept in synced browser storage), a refreshed design and accessible player controls. The API server must be running. When the API is remote, the popup asks for permission for that HTTPS origin; plain `http://` is accepted only for local addresses. Missing images fall back to a text card, and HTTP 429 shows a "Too many requests" message. See `docs/PRIVACY.md` and `docs/STORE_LISTING.md`.

## Environment variables

| Variable | Purpose | Default |
| :--- | :--- | :--- |
| `BIBLIONX_HOST` | Server bind address | `127.0.0.1` (`0.0.0.0` in Docker) |
| `BIBLIONX_PORT` | Server port | `8000` |
| `BIBLIONX_IMAGES_DIR` | Folder with sign PNGs | `<repo root>/extracted_images` (`/data/images` in Docker) |
| `BIBLIONX_RATE_PER_MIN` | Per-client requests per minute for translate and words; `0` disables | `120` |
| `BIBLIONX_TRUST_PROXY` | `1` reads client IP from `X-Forwarded-For` | off |
| `BIBLIONX_CORS_ORIGIN` | Allowed origins, comma-separated, or `*` | unset (same-origin only) |
| `BIBLIONX_METRICS` | `1`/`0` enables or disables `/api/v1/metrics` | on for localhost only |
| `BIBLIONX_DOMAIN` | Public domain for Caddy HTTPS (Compose only) | required in Compose |
| `BIBLIONX_IMAGES_HOST_DIR` | Host folder mounted as the images volume (Compose only) | `../extracted_images` |
| `BIBLIONX_LLM_PROVIDER` | `anthropic`, `openai` or `ollama`; empty disables AI | empty (off) |
| `BIBLIONX_LLM_MODEL` | Model override | provider default |
| `BIBLIONX_LLM_MAX_CALLS` | Max model calls per process; `0` is unlimited | `0` |
| `BIBLIONX_LLM_RATE_PER_MIN` | Max uncached model calls per minute; `0` is off (recommended `30`) | `0` |
| `ANTHROPIC_API_KEY` | Key for the `anthropic` provider | none |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Key and optional base URL for `openai` or compatible servers | none |
| `OLLAMA_URL` | Local Ollama endpoint | `http://127.0.0.1:11434` |

See `.env.example`.

## Tests and evaluation

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py                       # metrics on tests/data/eval_corpus.json
python scripts/evaluate.py --out metrics.json    # also writes JSON
python scripts/check_metrics.py                  # quality gate (coverage >= 0.85, recall >= 0.95)
python scripts/load_test.py                      # load test against a running server
```

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request (Python 3.12 and 3.13): unit tests, the evaluation quality gate, `node --check` on the extension and web JavaScript, and a scan for secret patterns.

### Validation with reviewers

`tools/export_review_sheets.py` exports curated synonyms, the Dominican lexicon, grammar rules and fuzzy matches to Spanish CSV sheets in `docs/validation/` so LSRD experts can review them. See `docs/validation/README.md` for the process. `docs/DICTIONARY_GAPS.md` lists frequent words with no sign and the pages to re-extract (`tools/find_dictionary_gaps.py`).

### Other documents

- `docs/DEPLOYMENT.md`: Docker, Compose, HTTPS.
- `docs/PRIVACY.md`: privacy policy for the API and the extension.
- `docs/STORE_LISTING.md`: browser store listing text.
- `CHANGELOG.md`: release notes.

### Metrics (134 evaluation sentences)

| Metric | Baseline | Current |
| :--- | :--- | :--- |
| Lexical coverage | 0.689 | 0.880 |
| Fingerspelled tokens | 151 | 57 |
| Unique fingerspelled words | 117 | 52 |
| Gold lemma recall | 0.797 | 0.975 |
| Avg ms per sentence | 19.6 | 2.2 |

Source: `tests/data/baseline_metrics.json` and `tests/data/after_metrics.json`. The evaluation corpus does not exercise the AI fallback.

---

## Developer Guide: Querying `lsrd_dictionary.db` Directly

The relational database has 5 main tables (column/table names are kept in Spanish — they're the live schema used across the NLP engine, API, and extension):
- `palabras` (id, lemma, normalized lemma, category, page).
- `categorias` (grammatical category names).
- `senas_descripciones` (movement / morphological description).
- `rutas_imagenes` (path of each sign PNG; the files themselves are not in the repo, see "Sign images are not distributed").
- `sinonimos_mapeo` (inflection variants and synonyms).

### Example 1: Query with the SQLite CLI
```bash
sqlite3 lsrd_dictionary.db "SELECT p.palabra_es, s.descripcion_sena FROM palabras p JOIN senas_descripciones s ON p.id = s.palabra_id WHERE p.palabra_norm = 'profesor';"
```

### Example 2: Query from a Python script
```python
import sqlite3

# Connect to the local DB inside the package
conn = sqlite3.connect("lsrd_dictionary.db")
cursor = conn.cursor()

# Search by keyword or lemma
cursor.execute("""
    SELECT p.id, p.palabra_es, c.nombre, s.descripcion_sena, r.ruta_imagen
    FROM palabras p
    LEFT JOIN categorias c ON p.categoria_id = c.id
    LEFT JOIN senas_descripciones s ON p.id = s.palabra_id
    LEFT JOIN rutas_imagenes r ON p.id = r.palabra_id
    WHERE p.palabra_norm = 'biblioteca'
""")

row = cursor.fetchone()
print(f"ID: {row[0]} | Sign: {row[1]} ({row[2]})")
print(f"Movement description: {row[3]}")
print(f"PNG image path: {row[4]}")
```

---

## Known limitations

- Question words (`como`, `donde`, `que`, ...) are kept in questions but have no signs in the dictionary, so they are fingerspelled.
- `sena`/`senas` are excluded from morphology and fuzzy matching to avoid false matches.
- About 2.6% of dictionary entries are flagged for manual review, and some basic words are missing from the source extraction.
- Fuzzy matching and the AI fallback are conservative on purpose; a wrong sign is worse than fingerspelling.

## Team

- [@MiraP7](https://github.com/MiraP7)
- [@Jose-hub-design](https://github.com/Jose-hub-design)
- [@wilkinvasquez](https://github.com/wilkinvasquez)

## Privacy and contributions

This is a public repository. Do not commit personal data, API keys, tokens or local paths.

## Origins

This project was initially forked from the open-source VLibras project. It has since evolved
enough to stand as an independent project of its own. Licensed under LGPLv3 — see [LICENSE](LICENSE).
