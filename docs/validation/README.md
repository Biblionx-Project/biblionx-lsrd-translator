# Validation review sheets

The translator combines a dictionary of LSRD signs with curated synonyms,
Dominican lexicon rules, grammar reordering rules and fuzzy matching. None of
those layers has been validated by Deaf signers yet. These CSV sheets let
LSRD interpreters and Deaf reviewers check them without touching code.

The sheets and their instructions are in Spanish (Dominican) because the
reviewers are Spanish-speaking. This README is for the maintainers.

## Sheets

| File | Source | Reviewer question |
|---|---|---|
| `00_instrucciones.csv` | fixed text | How to fill in the sheets (Spanish). |
| `01_sinonimos_curados.csv` | `data/synonyms_extra.json` | Can this Spanish word be shown with the target sign? |
| `02_lexico_dominicano.csv` | `data/dominican_lexicon.json` | Is the standard equivalent right, and is the resulting sign what you would use? |
| `03_reglas_gramatica.csv` | 30 sentences run through the full pipeline | Is the sign order natural LSRD? (time first, negation last, wh-words last, etc.) |
| `04_coincidencias_difusas.csv` | fuzzy matcher sample | Does the matched dictionary word mean the same as the input? |

Reviewer columns are `correcto (si/no)`, `seña sugerida` (`orden sugerido` in
the grammar sheet) and `comentarios`. Everything else is pre-filled.

Sheet 04 matters most: a wrong fuzzy match shows a wrong sign with no warning.
It mixes typos of dictionary words, frequent words the dictionary lacks, and
near misses the system currently rejects (`descartada`, which falls back to
fingerspelling).

## Who reviews

- At least two LSRD interpreters or Deaf native signers per sheet, ideally from
  different regions, so disagreements surface.
- A maintainer collects the files and resolves conflicts. A change is only
  applied when reviewers agree, or when a single reviewer is clearly right.
- Reviewers should not enter personal data in the comments.

## Generate / refresh

```
python tools/export_review_sheets.py                 # writes docs/validation/*.csv
python tools/export_review_sheets.py --delimiter ";" # Excel with Spain regional settings
```

Standard library only. Output is UTF-8 with BOM (Excel shows accents and the
letter n-tilde correctly) and is deterministic, so a diff of the CSVs shows
real data changes. The AI fallback is disabled during export. Re-run after
changing any `data/*.json`, the grammar rules or the database. Returned files
should be kept outside the repo unless the reviewers agree to publish them.

## Feeding corrections back

Apply decisions by editing data files, then run
`python -m unittest discover -s tests` and re-export the sheets.

| Sheet | Verdict | Action |
|---|---|---|
| 01 synonyms | `no` | Delete the entry from `data/synonyms_extra.json`. |
| 01 synonyms | `no` + suggested sign | Change `target_norm` and `palabra_id` to the suggested dictionary entry (`palabra_id` is in the sheet; look it up in `lsrd_dictionary.db`, table `palabras`). |
| 02 lexicon | `no` | Fix the value in `data/dominican_lexicon.json` (`orthographic` or `lexical`). Add new regional words to the same file. |
| 03 grammar | `no` | Rules live in `grammar.py` (`TIME_WORDS`, `NEGATION_WORDS`, `QUESTION_WORDS`, `reorder`). Reviewer corrections become test cases in `tests/` first, then code. Do not change a rule on one reviewer's word alone. |
| 04 fuzzy | `no` | Prevent the wrong substitution (add the word to a curated entry that points to the right sign, or extend `_is_wrong_neighbour` in `translator.py`). Never lower the threshold to fix one case. |
| 04 fuzzy | `si` | Optionally promote the pair to `data/synonyms_extra.json` so it stops depending on fuzzy scoring. |

A curated entry has this shape (`source` stays `curated`):

```json
{"word": "abuelita", "target_norm": "abuela", "palabra_id": "lsrd_0019", "source": "curated"}
```

## Related

`docs/DICTIONARY_GAPS.md` lists frequent Spanish words without a sign and the
dictionary pages to re-extract (`python tools/find_dictionary_gaps.py --out docs/DICTIONARY_GAPS.md`).
The sample pipeline output also shows that wh-words (como, donde, que, cuando,
quien) are currently fingerspelled and that "comer" resolves to COMIDA through a
curated synonym; both are worth a reviewer's opinion.
