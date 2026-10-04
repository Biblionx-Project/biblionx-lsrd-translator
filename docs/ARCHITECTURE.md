# Biblionx LSRD Translator: Architecture

Biblionx translates Spanish (Dominican Republic) text into Dominican Sign Language (LSRD) sign sequences. The core is pure Python (standard library only) and works on a read-only SQLite dictionary (`lsrd_dictionary.db`).

Origins: Biblionx was initially bootstrapped from the open-source VLibras project; it has since evolved into an independent development by the Biblionx team.

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
 |   llm_fallback.py optional AI choice (off)      |
 |   A-Z fingerspelling                            |
 +-------------------------+-----------------------+
                           v
        main.py (CLI)   backend_api/server.py (REST + /app/)
                                   ^
                      browser_extension/ (calls the API)
```

`process()` returns the same keys as the original engine, plus `normalized_text`, `is_question` and `lemmatization_methods`. `secuencia_lsrd` is a list subclass that also carries per-token method and sentence context.

Dictionary-derived indexes are built once per database path and shared read-only; each translator owns one SQLite connection guarded by a lock, so an instance can be shared across server threads.

`backend_api/` holds standalone copies of the engine, `data/` and the database so the server runs on its own. Keep them in sync with `python scripts/sync_backend.py` (`--check` reports differences). The LLM cache is never copied.

## Lookup chain

For each token the first hit wins:

1. **Exact**: `palabras.palabra_norm` equals the token (this includes merged phrase tokens).
2. **Dictionary synonym**: `sinonimos_mapeo.sinonimo_norm`.
3. **Curated synonym**: `data/synonyms_extra.json`.
4. **Fuzzy ML match**: character n-gram (2-4) TF-IDF cosine through an inverted index, reranked by normalized Damerau-Levenshtein with small bonuses. Guards: words of 3 characters or fewer, words with digits and protected words never fuzzy-match; a score threshold and bounded edit distance are required.
5. **AI choice** (optional): the model picks one index among the fuzzy candidates.
6. **Fingerspelling**: the word is spelled with the A-Z sign sequence.

Morphology runs earlier, in the NLP stage, and only returns a lemma that is reachable in the dictionary (or from an explicit irregular-verb map), so it cannot invent words without signs.

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
| `ai` | Candidate chosen by the optional LLM; also sets `matched_norm` | 0.7 |
| `fingerspelling` | No sign found, spelled letter by letter | 0.5 |

Clients can use `confidence` to highlight uncertain signs (for example in the web playground).

## AI fallback and cost

Disabled unless `BIBLIONX_LLM_PROVIDER` is `anthropic`, `openai` or `ollama`. Keys come only from environment variables (see `.env.example`); never commit them. Costs are bounded by: tiny prompts and output (an index among at most 12 candidates), an on-disk cache that also stores negative answers, a per-process call cap (`BIBLIONX_LLM_MAX_CALLS`), a short timeout, and silent fallback to fingerspelling on any error.

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
- `source`: `curated` for human-reviewed entries.

Workflow:

1. Run `python scripts/evaluate.py --out metrics.json` to list the most frequent fingerspelled words.
2. Run `python tools/suggest_synonyms.py --input metrics.json` (optionally `--use-llm`). It writes `data/synonyms_suggested.json` for review and never changes anything automatically.
3. A reviewer who knows LSRD checks each suggestion for true semantic equivalence, then copies approved entries into `synonyms_extra.json`.
4. Add a test case, run `python -m unittest discover -s tests`, re-run `evaluate.py`, then `python scripts/sync_backend.py`.

Prefer no synonym over a doubtful one: a wrong sign is worse than fingerspelling. Do not edit `lsrd_dictionary.db` to add synonyms.
