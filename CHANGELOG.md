# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.3.0] - 2026-10-23

Dictionary completion: every entry of the official PDF is in the database with its own headword, category, definition and movement description, and many more forms and Dominican words reach their sign.

### Changed
- `lsrd_dictionary.db` was audited against the PDF (`tools/apply_dictionary_fixes.py`, `data/dictionary_fixes.json`):
  578 field updates, 45 split headwords merged into one row (26 are the province entries on pages 430-436), 6 letter
  divider rows deleted and 45 sign images re-cropped. Rows went from 2,476 to 2,419; letter ids are unchanged.
  Rows without a movement description 256 to 0, without a definition 63 to 43, `Sin Categoría` 148 to 37, split
  headwords 45 to 0. The 48 rows flagged `requiere_revision` are fields the PDF never prints (mostly the 34 provinces).
- Generic morphology rules (`b3ac4db`): reflexive-only verbs (ABURRIRSE) from their conjugations, vowel changes only for
  verbs that have them, irregular -uir, oler, reír and tener/poner/decir/hacer compounds, feminine and diminutive forms,
  -mente, -ísimo and Dominican -ao, accent-aware verb forms and plural or conjugated phrases. Of 685 forms the A-Z reach
  audits found unreachable, 398 now reach their sign (79 before).
- CI gates tightened to just below the 2.3.0 values (precision gate raised, none loosened), see Metrics.

### Added
- 1,247 single-word synonyms in `data/synonyms_extra.json` (now 2,221 entries), all `curated-pending-review`, merged with
  `tools/merge_synonym_proposals.py` (conflict rules covered by `tests/test_synonym_merge.py`). The final review dropped 50
  more as homographs or meaning shifts (`REVIEW_REJECTED`: e.g. super, evacuar, índice, pacífico, grano, ingreso). 106 multi-word proposals
  wait in `data/synonyms_phrases_pending.json` until they are added to `sinonimos_mapeo`. The five Spanish review sheets in
  `docs/validation/` were regenerated.
- Dictionary completeness report and reachability rate per alphabet range in `docs/DICTIONARY_GAPS.md`.
- Saved evaluation runs `tests/data/after_metrics_v23.json` and `tests/data/realistic_v23.json`.

### Metrics
Same corpora, `python scripts/evaluate.py` (saved v2.2.0 runs: `tests/data/after_metrics.json`, `tests/data/realistic_after.json`).

| Corpus | Measure | 2.2.0 | 2.3.0 | CI gate (was) |
|---|---|---|---|---|
| Gold, 134 sentences | lexical coverage | 0.9146 | 0.9169 | >= 0.90 (0.88) |
| | fingerspelling rate | 0.0854 | 0.0831 | <= 0.10 (0.12) |
| | gold lemma recall | 0.9747 | 0.9747 | >= 0.97 (0.95) |
| | gold lemma precision | 0.9655 | 0.9569 | >= 0.95 (0.93) |
| | order accuracy | 1.0 | 1.0 | >= 1.0 |
| | avg ms per sentence | 1.65 | 1.76 | p95 <= 500 |
| Realistic, 42 paragraphs | lexical coverage | 0.7562 | 0.7763 | >= 0.77 (0.75) |
| | common-word fingerspelling | 0.2303 | 0.2094 | <= 0.215 (0.235) |
| | letters per lexical sign | 2.446 | 2.194 | |
| | fingerspelled words | 206 | 189 | |

Gold precision is 0.0086 below the saved 2.2.0 run. The extra content signs are "vivo" (2), "comer", "comimos" and "habichuela"
(1 each); recall is unchanged.

### Fixed
- Fuzzy matching indexed the gender suffix of headwords ('da', 'ra', 'tras') as words, so the preposition
  "tras" became NOSOTROS, TRAS. Suffixes now only produce the feminine form ('nosotras'); "tras" is a stopword.
- Multi-word proper nouns now also use `sinonimos_mapeo` (names printed inside a headword), so "Puerto Plata" and
  "Santiago de los Caballeros" reach their province sign; curated synonyms are still never used for names.
- `test_ids_are_contiguous` allows exactly the gaps recorded in the `id_map` of `data/dictionary_fixes.json`.
- Second-sign captions stay as printed: pages 39, 41, 43 and 58 print "SEÑA NÚMERO DOS", the rest "SEÑA NUMERO DOS".

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
- Realistic evaluation corpus `tests/data/eval_corpus_realistic.json`: 42 original paragraphs of 2-4 sentences in the
  registers people select on Dominican web pages (encyclopedic, local news, school notices, health, government, sports,
  weather, informal social media with dominicanisms), each tagged with `register` and `has_proper_nouns`. It has no gold
  lemmas; it measures how much real text ends up fingerspelled. Saved runs: `tests/data/realistic_baseline.json`
  (before the work below) and `tests/data/realistic_after.json`.
- `evaluate.py` accepts several `--corpus` files and reports each one (`corpora` object keyed by file name; the top
  level still mirrors the first corpus, so existing readers and gates are unchanged). New metrics (`metrics_version` 3):
  `fingerspelled_word_rate` (words, not letters), `fingerspelled_letters`, `letters_per_lexical_sign`, and the split of
  spelled words into proper nouns (capitalized mid-sentence in the original text) and common words, with
  `common_fingerspelled_word_rate` as the figure that matters (proper nouns are legitimately spelled). Also per tag.
- `check_metrics.py`: `--corpus NAME` selects one corpus of a multi-corpus file and `--max-common-fingerspelling-rate`
  gates common-word spelling; a corpus without gold lemmas is not failed on recall. CI gates the realistic corpus
  (coverage >= 0.76, common-word fingerspelling <= 0.23).
- Optional semantic AI fallback (`llm_fallback.choose_semantic`): the model receives the word, its sentence and the whole
  list of sign lemmas as a prompt-cached block and may only answer with an existing lemma or `NONE`. Cached on disk
  (negatives too), subject to the call cap and rate limit, confidence capped at 0.6. Off by default and never used by
  the evaluation.
- Fingerspelled letter items carry `spelled_word`, `spelled_index` and `spelled_length`, so clients can group the
  letters of one word (see `docs/ARCHITECTURE.md`).
- 707 curated mappings in `data/synonyms_extra.json`, all `curated-pending-review`, linking previously fingerspelled
  derived forms to an existing sign (for example llover to LLUVIA, recomendar to RECOMENDACION, central to CENTRO,
  poblada to PUEBLO). Meaning shifts (poder, publico) and proper nouns stay unmapped. `tools/expand_vocabulary.py`
  proposes further candidates into `data/vocabulary_candidates.json` for interpreter review.

### Changed
- Browser extension (Manifest V3): accessibility improvements.
- The project was rebranded to Biblionx; VLibras is kept only as a fork note.
- `evaluate.py` now keeps morphology and phrase provenance per token instead of reporting everything as `exact`.
- Lexical coverage 0.8795 to 0.9070; fingerspelled tokens 57 to 44; gold lemma recall stays 0.9747.
- The server, the extension manifest and the OpenAPI spec now all report the same version.
- The AI fallback no longer chooses among fuzzy spelling neighbours inside the translator; it is the semantic fallback
  described above (the neighbour-index `choose()` remains for `tools/suggest_synonyms.py`). AI match confidence is
  capped at 0.6 (was 0.7).
- Signless function words are dropped instead of fingerspelled: object clitics (lo, le, les, os), relative forms
  (cuales, quienes, cuyo), prepositions (ante, hacia, segun, desde, hasta) and connectors (aunque, pues, sino);
  `haber` is treated as an auxiliary. Words that own a sign (mi, te, me, nos, ni, no) are kept.
- The web player and the browser extension show one timeline chip per fingerspelled word (current letter highlighted,
  per-word progress, caption) instead of one slot per letter.
- Realistic text, before to after this work (42 paragraphs): lexical coverage 0.7015 to 0.7802, fingerspelled words
  280 to 204, fingerspelled letters 2,067 to 1,515, letters per lexical sign 3.14 to 2.09, common-word fingerspelling
  rate 0.2887 to 0.2103. The corpus was visible to the vocabulary harvest, so it is a development set; on 12 unseen
  paragraphs the common-word rate went from 0.2996 to 0.2536. Gold corpus: fingerspelling rate 0.0930 to 0.0787.

### Fixed
- Curated synonyms now steer the lemmatizer: "duele" no longer becomes DÓLAR (it maps to DOLOR) and "gusta" reaches
  ME GUSTA through "gustar". Ten curated mappings with a meaning shift were removed (ciudadano, empleado, sujeto, mismo,
  recepcion, interes, fruto and their forms).
- The image test was silently skipped in CI because `extracted_images/` is not tracked.
- About half of the local sign images (1,228 of 2,458) were crops of dictionary text instead of the sign illustration,
  a systematic error of the original extraction. `tools/recrop_sign_images.py` regenerates every image from the official
  PDF (pdfminer.six + pypdfium2) with a skin-tone QA check; `tests/test_image_quality.py` guards it and
  `docs/IMAGES.md` documents the process. Images remain outside git.
- "año" was translated as ANO and "sonar" as SOÑAR: normalization drops ñ, so ñ words collided with other
  headwords ("uña" was even dropped as the article "una"). Lookups now use the printed headword with ñ kept, and a
  word written without ñ never matches a headword that has one. Fingerspelling keeps Ñ (ESPAÑOLA, not ESPANOLA).
- Proper nouns were matched to common words ("Mona" -> MONO, "Puerto Rico" -> P-U-E-R-T-O + RICO). Capitalized
  words that do not start a sentence are grouped as names: a name uses only its own dictionary entry (Santo
  Domingo, Puerto Plata), is signed word by word when every word has a sign (Ministerio de Educación), and is
  otherwise fingerspelled whole.
- Numerals produced no signs at all. 1-10, 100 and 1000 use their number signs; other numbers (years) are signed
  digit by digit (`match_method` `number`).
- The preposition "a" and the conjunctions "y", "o", "e", "u" were shown as the letter signs A, Y, O, E, U (the
  dictionary has them only as letters); they are now dropped like other function words. This also removes ~75
  false "exact" matches from the realistic corpus, so its coverage gate is now 0.75 (measured 0.7562) and the
  common-word fingerspelling gate 0.235 (measured 0.2303) with the same number of spelled common words.
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
