# Biblionx LSRD Translator

Biblionx translates Spanish text, including Dominican Spanish, into **Dominican Sign Language (Lengua de Senas Republicana Dominicana, LSRD)** sign sequences. It ships a Python translation engine (standard library only), a REST API, a web playground and a browser extension.

> The translation input is Spanish (Dominican Republic) and the output is LSRD. Documentation, code and comments are in English; dictionary data and sign descriptions stay in Spanish because they are primary-source data from the official LSRD dictionary.

## Origins

Biblionx was initially bootstrapped from the open-source VLibras project; it has since evolved into an independent development by the Biblionx team.

## What is in this repository

| Path | Description |
| :--- | :--- |
| `lsrd_dictionary.db` | SQLite database: 2,458 lemmas, categories, movement descriptions, image paths. Read-only data. |
| `extracted_images/` | One PNG per sign (`lsrd_0001.png` ...). |
| `main.py` | Interactive console translator. |
| `nlp_engine.py` | Text pipeline: normalization, phrases, morphology, grammar. |
| `translator.py` | Lookup chain from tokens to signs, with provenance and confidence. |
| `dominican_lexicon.py`, `phrases.py`, `morphology.py`, `grammar.py` | Pipeline stages. |
| `ml_matcher.py` | Pure Python fuzzy matcher (character n-gram TF-IDF). |
| `llm_fallback.py` | Optional, off-by-default AI fallback. |
| `data/` | `dominican_lexicon.json` and curated `synonyms_extra.json`. |
| `backend_api/` | Standalone HTTP server, web playground, and synced copies of the engine. |
| `browser_extension/` | Manifest V3 extension (v2). |
| `scripts/` | `evaluate.py` (metrics) and `sync_backend.py` (copy engine into `backend_api/`). |
| `tools/suggest_synonyms.py` | Reviewer helper that proposes synonyms for unknown words. |
| `tests/` | Unit tests and the evaluation corpus. |
| `docs/ARCHITECTURE.md` | Modules, lookup chain, confidence semantics, synonym curation. |

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
- A hard cap on calls per process (`BIBLIONX_LLM_MAX_CALLS`, default 50).
- Any error falls back to fingerspelling.

Configure it only through environment variables; see `.env.example`. **Never commit API keys or a real `.env` file.** Keys are read from the environment and are never logged or written to disk.

## Quick start

Python 3 and the standard library are enough; no `pip install`.

```bash
python main.py                          # interactive console
cd backend_api && python server.py      # API + web playground
```

Then open `http://127.0.0.1:8000/app/`.

### Web playground (`/app/`)

A responsive, accessible UI with light and dark themes: type or pick an example sentence, see the gloss timeline, play the sign sequence with previous/next/speed controls, and inspect each sign's description, dictionary page and match confidence.

### API

- `POST /api/v1/translate` with `{"texto": "..."}` returns the analysis and `secuencia_senas`.
- `GET /api/v1/words/{lemma}` direct dictionary lookup.
- `GET /api/v1/health` health check.
- `GET /app/` web playground; `GET /extracted_images/{id}.png` sign images.

### Browser extension (v2)

Load `browser_extension/` as an unpacked extension (`chrome://extensions`, Developer Mode). Select text on any page and use the floating button or the "Translate to LSRD" context menu to open the sign player overlay. v2 adds adjustable playback speed, a settings popup (API base URL and default speed, kept in synced browser storage), a refreshed design and accessible player controls. The API server must be running.

## Environment variables

| Variable | Purpose | Default |
| :--- | :--- | :--- |
| `BIBLIONX_HOST` | Server bind address | `127.0.0.1` |
| `BIBLIONX_PORT` | Server port | `8000` |
| `BIBLIONX_CORS_ORIGIN` | `Access-Control-Allow-Origin` value | `*` |
| `BIBLIONX_LLM_PROVIDER` | `anthropic`, `openai` or `ollama`; empty disables AI | empty (off) |
| `BIBLIONX_LLM_MODEL` | Model override | provider default |
| `BIBLIONX_LLM_MAX_CALLS` | Max model calls per process | `50` |
| `ANTHROPIC_API_KEY` | Key for the `anthropic` provider | none |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Key and optional base URL for `openai` or compatible servers | none |
| `OLLAMA_URL` | Local Ollama endpoint | `http://127.0.0.1:11434` |

## Tests and evaluation

```bash
python -m unittest discover -s tests -v
python scripts/evaluate.py                       # metrics on tests/data/eval_corpus.json
python scripts/evaluate.py --out metrics.json    # also writes JSON
python scripts/sync_backend.py                   # refresh backend_api/ copies (--check to diff only)
```

Run `sync_backend.py` after changing engine modules or data so `backend_api/` stays identical.

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
- `rutas_imagenes` (path to the PNG files in `extracted_images/`).
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
print(f"PNG image: {row[4]}")
```

---


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

## License

Distributed under the GNU Lesser General Public License v3.0; see `LICENSE`. Code derived from the upstream VLibras project retains its original license terms.
