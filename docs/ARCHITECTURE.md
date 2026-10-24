# Biblionx LSRD Translator: Architecture

Biblionx translates Spanish (Dominican Republic) text into Dominican Sign Language (LSRD) sign sequences. The core is pure Python (standard library only) and works on a read-only SQLite dictionary (`lsrd_dictionary.db`).

## Module diagram

```
                 Spanish text
                      |
                      v
 +-------------------------------------------------+
 | nlp_engine.py  LSRDNlpEngine.process()          |
 |   dominican_lexicon.py  normalize_text          |
 |   clause split + tokenize/normalize             |
 |   phrases.py            phrase segmentation     |
 |   stopword removal (wh-words kept in questions) |
 |   morphology.py         lemmatization           |
 |   grammar.py            LSRD reordering         |
 +-------------------------+-----------------------+
                           | secuencia_lsrd (tokens + provenance)
                           v
 +-------------------------------------------------+
 | translator.py  lookup chain                     |
 |   in-memory indexes from lsrd_dictionary.db     |
 |   data/synonyms_extra.json  curated synonyms    |
 |   ml_matcher.py   fuzzy char n-gram TF-IDF      |
 |   llm_fallback.py optional semantic AI (off)    |
 |   A-Z fingerspelling                            |
 +-------------------------+-----------------------+
                           v
        main.py (CLI)   backend_api/server.py (REST + /app/)
                          |  imports the repo root (no copies)
                          |  rate limit, CORS, security headers, logs
                          |  GET /extracted_images/* <-- BIBLIONX_IMAGES_DIR
                          ^
        browser_extension/ (service worker calls the API)
```

## Runtime

```
 Browser (web playground /app/)      Extension service worker
              \                          /
               +----- HTTPS (Caddy) ----+      <- deploy/Caddyfile
                           |
                  backend_api/server.py  (ThreadingHTTPServer, non-root in Docker)
                    |            |                |
        root engine modules   lsrd_dictionary.db   BIBLIONX_IMAGES_DIR (read-only volume,
        (nlp_engine, ...)     (read-only)          not in git; optional)
```

`backend_api/` contains only `server.py` and `web/`. It adds the repository root to `sys.path` and imports the engine, `data/` and the database from there, so there is nothing to synchronize (`scripts/sync_backend.py` was removed).

### Sign images

Images were extraction artifacts used to build the database and are not distributed in git. The server serves them from `BIBLIONX_IMAGES_DIR` (default `<repo root>/extracted_images`). If a file is missing, each sign in a translate response carries `image_available: false` and no `url_imagen`; clients render a text card (word plus Spanish movement description).

### Server hardening

Per-client rate limiting (`BIBLIONX_RATE_PER_MIN`, 429 with `Retry-After`), same-origin CORS unless `BIBLIONX_CORS_ORIGIN` is set, security headers plus a strict CSP on `/app/`, JSON request logs with hashed client and request id (never the submitted text), and `/api/v1/metrics` (`BIBLIONX_METRICS`). `BIBLIONX_TRUST_PROXY=1` is for deployments behind a reverse proxy. See `docs/openapi.yaml` and `docs/DEPLOYMENT.md`.

`process()` returns the same keys as the original engine, plus `normalized_text`, `is_question` and `lemmatization_methods`. `secuencia_lsrd` is a list subclass that also carries per-token method and sentence context.

Dictionary-derived indexes are built once per database path and shared read-only; each translator owns one SQLite connection guarded by a lock, so an instance can be shared across server threads.

The LLM cache (`data/.llm_cache.json`) is never committed.

## Lookup chain

For each token the first hit wins:

1. **Exact**: `palabras.palabra_norm` equals the token (this includes merged phrase tokens).
2. **Dictionary synonym**: `sinonimos_mapeo.sinonimo_norm`.
3. **Curated synonym**: `data/synonyms_extra.json` (about 2,270 entries; those with `source: curated-pending-review` link a derived or related form to an existing sign and still need interpreter validation).
4. **Fuzzy ML match**: character n-gram (2-4) TF-IDF cosine through an inverted index, reranked by normalized Damerau-Levenshtein with small bonuses. Guards: words of 3 characters or fewer, words with digits and protected words never fuzzy-match; a score threshold and bounded edit distance are required.
5. **Semantic AI choice** (optional, off by default): when every deterministic step missed, the model receives the word, its sentence and the complete list of dictionary sign lemmas, and must answer with exactly one listed lemma or `NONE`. The answer is validated against that list, so the model can only select a sign that exists; function words and proper names without a sign are answered `NONE`. Confidence is capped at 0.6. See "AI fallback and cost" below.
6. **Fingerspelling**: the word is spelled with the A-Z sign sequence (grouped per word, see below).

Before the lookup, the NLP stage drops function words that have no sign of their own (`LSRD_STOP_WORDS` in `nlp_engine.py`: articles, object clitics `lo/le/les`, signless prepositions and connectors) and the auxiliaries in `AUXILIARY_VERBS`; a word that owns a sign is never dropped. Morphology runs in the same stage, and only returns a lemma that is reachable in the dictionary (or from an explicit irregular-verb map), so it cannot invent words without signs.

## match_method and confidence

Every sign returned by the translator includes `match_method` and `confidence` (0 to 1). Confidence expresses how much to trust the mapping, not translation quality.

| `match_method` | Meaning | `confidence` |
| :--- | :--- | :--- |
| `exact` | Direct dictionary entry | 1.0 |
| `phrase` | Multi-word entry matched as one sign | 0.95 |
| `morphology` | Lemma found via conjugation, plural, gender or diminutive rules | 0.9 |
| `synonym` | `sinonimos_mapeo` entry | 0.9 |
| `curated_synonym` | Reviewed entry from `synonyms_extra.json` | 0.85 |
| `fuzzy` | ML nearest neighbour; also sets `matched_norm` | the match score |
| `ai` | Existing lemma chosen by the optional semantic AI fallback; also sets `matched_norm` | at most 0.6 |
| `fingerspelling` | No sign found, spelled letter by letter | 0.5 |

Clients can use `confidence` to highlight uncertain signs (for example in the web playground).

## Fingerspelling contract (grouped by word)

A word with no sign is returned as one item per letter, in order, each with `es_deletreo: true`, `letra` (the upper-case letter), `match_method: "fingerspelling"` and `confidence: 0.5`. Since 2.2.0 every letter item also carries:

| Field | Meaning |
| :--- | :--- |
| `spelled_word` | The token being spelled (identical on every letter of that word) |
| `spelled_index` | 0-based position of the letter among the letters emitted for the word |
| `spelled_length` | Number of letter items emitted for the word (characters without a letter sign, such as digits, are skipped and not counted) |

The API stays a flat list, so older clients keep working. UIs (`backend_api/web/app.js`, `browser_extension/content.js`) use these fields to show one timeline chip per spelled word, with the current letter highlighted, a per-word progress counter and a "fingerspelled" caption, instead of one slot per letter. When the fields are absent (an older server), they merge consecutive `es_deletreo` items instead. Consumers that need counts must therefore count words with `spelled_word` (or runs of `es_deletreo`), not letters; `scripts/evaluate.py` reports both (`fingerspelled_tokens` versus `fingerspelled_letters`).

## AI fallback and cost

Disabled unless `BIBLIONX_LLM_PROVIDER` is `anthropic`, `openai` or `ollama`. Keys come only from environment variables (see `.env.example`); never commit them. It runs after the exact, synonym, curated and fuzzy steps and before fingerspelling, only for tokens of at least 3 characters without digits and not protected.

`llm_fallback.LLMFallback.choose_semantic()` builds one stable system block with the instructions and every dictionary sign lemma (deduplicated and sorted, letter signs excluded), and sends the word plus its sentence (at most 300 characters) as the only variable part. With Anthropic the block carries `cache_control: ephemeral`, so repeated calls pay cache-read prices; OpenAI caches long prefixes automatically; Ollama receives a larger context window. The reply is parsed against the lemma list (accent and case insensitive), so prose, `NONE` and invented lemmas all resolve to "no match" and the word is fingerspelled. The older `choose()` (an index among at most 12 fuzzy candidates) remains for `tools/suggest_synonyms.py`.

Costs are bounded by: a tiny answer (24 output tokens), the cached prompt prefix, an on-disk cache that also stores negative answers (the key includes the sentence and a hash of the vocabulary, so a changed dictionary never reuses stale answers), an optional per-process call cap (`BIBLIONX_LLM_MAX_CALLS`, default 0 = unlimited so demos translate broadly), an optional rate limit (`BIBLIONX_LLM_RATE_PER_MIN`, default off; 30 recommended for public deployments together with a monthly spend limit in the provider console), a short timeout, and silent fallback to fingerspelling on any error. `scripts/evaluate.py` clears the `BIBLIONX_LLM_*` variables, so the published metrics never include AI matches and stay deterministic and free.

## How to curate synonyms

Curated synonyms live in `data/synonyms_extra.json`:

```json
{
  "version": 1,
  "entries": [
    {"word": "auto", "target_norm": "carro", "palabra_id": "lsrd_0437", "source": "curated"}
  ]
}
```

- `word`: normalized input form (lowercase, no accents).
- `target_norm`: the `palabra_norm` of the dictionary entry it should resolve to.
- `palabra_id`: that entry's id; verify it in the database.
- `source`: `curated` for human-reviewed entries, `curated-pending-review` for mappings waiting for an interpreter. Only link a word to an existing sign when the meaning is the same or it is the standard LSRD way to express it (a noun/verb pair such as lluvia/llover usually shares one sign).

Workflow:

1. Run `python scripts/evaluate.py --out metrics.json` to list the most frequent fingerspelled words.
2. Run `python tools/suggest_synonyms.py --input metrics.json` (optionally `--use-llm`). It writes `data/synonyms_suggested.json` for review and never changes anything automatically.
3. A reviewer who knows LSRD checks each suggestion for true semantic equivalence, then copies approved entries into `synonyms_extra.json`.
4. Add a test case, run `python -m unittest discover -s tests`, re-run `evaluate.py`, then run `python scripts/check_metrics.py`.

Prefer no synonym over a doubtful one: a wrong sign is worse than fingerspelling. Do not edit `lsrd_dictionary.db` to add synonyms.

## Quality and validation

CI (`.github/workflows/ci.yml`) runs the tests and the metrics gates (`scripts/check_metrics.py`). Expert review sheets live in `docs/validation/` (generated by `tools/export_review_sheets.py`), and dictionary gaps are tracked in `docs/DICTIONARY_GAPS.md`.

Two corpora are evaluated by `python scripts/evaluate.py --corpus tests/data/eval_corpus.json --corpus tests/data/eval_corpus_realistic.json`:

- `eval_corpus.json`: short gold sentences with expected lemmas and order; gates coverage, lemma recall and precision, order accuracy and latency.
- `eval_corpus_realistic.json`: 42 original 2-4 sentence paragraphs in the registers people select on web pages (encyclopedic, local news, school notices, health, government, sports, weather, informal social media). It has no gold lemmas; it answers "how much of real text is fingerspelled". The figure to watch is `common_fingerspelled_word_rate`: spelled words that are not proper nouns (capitalized mid-sentence in the source text, or acronyms) over all non-proper words. Proper nouns are legitimately spelled and reported separately. `letters_per_lexical_sign` shows the visual cost of spelling: how many letter signs a reader sees per lexical sign.

`tests/data/realistic_baseline.json` (translator at 4e9d492) and `tests/data/realistic_after.json` (with the semantic fallback code, function-word dropping and the 707 curated mappings) record the improvement of 2.1 and 2.2 (the saved 2.2.0 run measured coverage 0.7562 and common-word spelling 0.2303 after proper nouns and one-letter function words stopped matching signs by accident). `tests/data/realistic_v23.json` and `tests/data/after_metrics_v23.json` are the 2.3.0 runs (dictionary completion, 1,297 more curated synonyms and the generic morphology rules): realistic coverage 0.7799, common-word spelling 0.2057, letters per lexical sign 2.16; gold coverage 0.9146, recall 0.9747, precision 0.9565. The vocabulary harvest (`tools/expand_vocabulary.py`) reads `tests/data/eval_corpus*.json`, so this corpus is a development set; keep an unseen paragraph set aside when judging new vocabulary work. The evaluation never calls an AI provider, so these figures are deterministic.
