# Dictionary gaps: verified status

This page records which frequent Spanish words have no sign in `lsrd_dictionary.db`, and why.
Each status below was checked against the official source, the *Diccionario Oficial de la
Lengua de Señas Dominicana* (first edition, 437-page PDF). It is not an estimate.

## How it was verified

1. `tools/recover_dictionary_entries.py` parses every entry on every page of the PDF. It reads
   text lines with their font and position: headwords are Poppins ExtraBold at about 18 pt,
   categories are Poppins Light at 6 pt, definitions are SemiBold and movement descriptions are
   Regular at 9 pt. It then compares the parsed entries with `palabras` (lowercase, accents
   removed). The PDF yields 2,423 entries, and 18 of them were missing from the database.
   Another 42 headwords were in the database as several rows each (the original extraction
   split them by printed line, for example `PERAVIA` + `(BANÍ)`). Version 2.3.0 merged them, see
   the completeness report below.
2. The 18 missing entries were inserted with `--apply` (ids `lsrd_2459` to `lsrd_2476`). Their
   illustrations were cropped from the PDF into the local, untracked `extracted_images/` folder.
   No existing row, id or category changed. Re-running the tool inserts nothing.
3. `tools/find_dictionary_gaps.py` lists frequent words that still do not resolve. Every word
   below was confirmed to have **no headword in the PDF**. For some of them a closely related
   dictionary sign exists, and those were added to `data/synonyms_extra.json` with
   `"source": "curated-pending-review"`. They appear in the interpreter review sheets
   (`tools/export_review_sheets.py`). They must be validated by LSRD interpreters or Deaf
   reviewers before they count as confirmed. The others stay fingerspelled. No sign was invented.

Most of the missing entries come from the left-hand pages of PDF pages 196-199 and 414. On those
pages the text column sits on the left and the picture on the right, the reverse of the usual
layout, and the original extraction skipped every entry on them. DICCIONARIO (page 143) was a
single miss.

## Summary

| Status | Count |
|---|---|
| Entries recovered from the PDF (total) | 18 |
| of which in the 421-word frequency list (GRANDE) | 1 |
| Frequent words not in the dictionary, mapped to a related sign (pending review) | 24 |
| Frequent words not in the dictionary, fingerspelled | 69 |
| Frequency-list gaps before / after | 94 / 69 |

`COMER` also has no entry (PDF page 113 goes from COMERCIO to COMIDA). It was already mapped to
COMIDA in the curated list before this work.

Evaluation corpus (`python scripts/evaluate.py`, 134 sentences), before and after this change:
lexical coverage went from 0.8985 to 0.9070, gold lemma recall stayed at 0.9747, and
fingerspelled tokens went from 48 to 44.

## Recovered entries

| Id | Headword | PDF page | Note |
|---|---|---|---|
| lsrd_2459 | DICCIONARIO | 143 | |
| lsrd_2460 | GRANDE | 196 | frequent word |
| lsrd_2461 | GRANIZO | 196 | |
| lsrd_2462 | GRAPA | 196 | shares sign and description with GRAPADORA, GRAPAR |
| lsrd_2463 | GRAPADORA | 196 | shared sign |
| lsrd_2464 | GRAPAR | 196 | shared sign |
| lsrd_2465 | GRITAR | 197 | |
| lsrd_2466 | GROSERO, RA | 197 | |
| lsrd_2467 | GRÚA | 197 | |
| lsrd_2468 | GUANDUL | 198 | |
| lsrd_2469 | GUANTE | 198 | |
| lsrd_2470 | GUANTE (DEPORTE) | 198 | baseball glove |
| lsrd_2471 | GUERRA | 199 | |
| lsrd_2472 | GUIAR | 199 | |
| lsrd_2473 | GUINEO | 199 | |
| lsrd_2474 | LOCRIO DE POLLO | 414 | multi-word entry |
| lsrd_2475 | MANGA CORTA | 414 | multi-word entry |
| lsrd_2476 | MANGA LARGA | 414 | multi-word entry |

All 18 rows have a category, a definition, a movement description and an image path, and they
are stored with `requiere_revision = 0`.

## Not in the dictionary: mapped to a related sign (pending review)

| Word | Mapped to | Id | Basis |
|---|---|---|---|
| jugar | JUEGO | lsrd_1234 | same word family (verb of the noun) |
| cocinar | COCINA | lsrd_0528 | same word family |
| respuesta | RESPONDER | lsrd_1879 | dictionary defines RESPONDER as "Contestar, dar una respuesta" |
| contestar | RESPONDER | lsrd_1879 | same definition |
| madre | MAMÁ | lsrd_1343 | dictionary defines MAMÁ as "Madre, ..." |
| padre | PAPÁ | lsrd_1604 | dictionary defines PAPÁ as "Padre, progenitor ..."; PADRE (CATÓLICO) is the priest sign |
| resolver | SOLUCIONAR | lsrd_2001 | dictionary defines SOLUCIONAR as "Resolver un problema" |
| empresa | COMPAÑIA | lsrd_0554 | COMPAÑIA is defined as a commercial organisation |
| comprender | ENTENDER | lsrd_0865 | synonym |
| oír | ESCUCHAR | lsrd_0906 | closest entry (first of the two ESCUCHAR signs) |
| sentar | SENTARSE | lsrd_1954 | pronominal entry of the same verb |
| quedar | QUEDARSE | lsrd_1800 | pronominal entry of the same verb |
| gustar | ME GUSTA | lsrd_2324 | fixed expression in the dictionary |
| alegría | ALEGRE | lsrd_0107 | same word family |
| importancia | IMPORTANTE | lsrd_1169 | same word family |
| necesario | NECESITAR | lsrd_1490 | same word family |
| prometer | PROMESA | lsrd_1782 | same word family |
| reunir | REUNIÓN | lsrd_1887 | same word family |
| ejercitar | EJERCICIO | lsrd_0817 | same word family |
| visitar | VISITA | lsrd_2227 | same word family |
| faltar | FALTA | lsrd_0980 | same word family ("Carencia o ausencia de algo") |
| morir | MUERTE | lsrd_1463 | same word family |
| cercano | CERCA | lsrd_0468 | same word family |
| cuidadoso | CUIDADO | lsrd_0664 | same word family |

Reviewers should confirm that LSRD really uses the related sign for each word. A
noun-for-verb substitution is common in sign languages, but it is not guaranteed. If a mapping
is rejected, delete its entry and the word goes back to fingerspelling.

## Not in the dictionary: fingerspelled

No related entry is close enough to use without inventing a sign:

- **Nouns:** CONVERSACIÓN, COSA, EJEMPLO, FIESTA, INVIERNO, JARDÍN, MOMENTO, NAVIDAD, NIÑA,
  NIÑO, NOCHE, PELÍCULA, PROGRAMA, RATO, RAZÓN, REY, SEÑAL, SEÑOR, SEÑORA, SOMBRA, SONIDO,
  SUERTE, VOZ
- **Verbs:** AGRADECER, DECIDIR, DESPERTAR, EXISTIR, GANAR, HABER, HACER, IMPORTAR, MANDAR,
  NOTAR, OBTENER, PERDER, PERMITIR, PODER, PROTEGER, SACAR, SEGUIR, SER, SERVIR, SUBIR
- **Adjectives:** AMABLE, ANTIGUO, BONITO, CORTO, ENORME, ESTRECHO, FEO, GRACIOSO, HERMOSO,
  LIBRE, LISTO, MORENO, OSCURO, POBRE, POSIBLE, SANO, ÚTIL
- **Adverbs:** ADEMÁS, BASTANTE, CLARAMENTE, ESPECIALMENTE, FINALMENTE, GENERALMENTE, MIENTRAS,
  REALMENTE, TAMPOCO

Several of these are function words (SER, HABER, HACER) that LSRD usually leaves out or
expresses through grammar, not with a lexical sign. Others, such as NIÑO, PODER, BONITO and
NOCHE, are good candidates to collect from interpreters, because a second edition of the
dictionary or field recordings could add them.

## Dictionary completeness report (version 2.3.0)

Version 2.3.0 audited every printed entry of the PDF against `lsrd_dictionary.db` and fixed the
fields the original extraction got wrong. Only the PDF was used as a source: no sign and no
description was invented, and the Spanish dictionary text is kept exactly as printed. The
letter ids used by fingerspelling did not change.

### Entries in the PDF versus the database

| Measure | Before (2.2.0) | After (2.3.0) |
|---|---|---|
| Entry lines parsed from the PDF by `tools/recover_dictionary_entries.py` | 2,423 | 2,423 |
| Distinct entries in the PDF (a headword printed on several lines counts once) | 2,419 | 2,419 |
| Rows in `palabras` | 2,476 | 2,419 |
| Rows with an image file on disk | all | all (45 re-cropped) |
| Rows without a movement description | 256 | 0 |
| Rows without a definition | 63 | 43 |
| Rows in `Sin Categoría` | 148 | 37 |
| Headwords split across several rows | 45 | 0 |
| Rows flagged `requiere_revision` | 63 | 48 |

The parser still lists 8 "missing" lines. They are fragments of 4 entries that the PDF prints over
two lines (MASTURBACIÓN FEMENINA, MASTURBACIÓN MASCULINA, FRANCISCO DEL ROSARIO SÁNCHEZ and
MARIA TRINIDAD SANCHEZ (NAGUA)); each is one merged row in the database (`lsrd_2321`,
`lsrd_2323`, `lsrd_2361`, `lsrd_2425`). So every printed entry is present exactly once.

What changed (`tools/apply_dictionary_fixes.py`, data in `data/dictionary_fixes.json`): 578 field
updates, 45 merges of split headwords (26 of them the province entries on pages 430-436), 6
deleted letter-divider rows and 45 re-cropped images. The PDF has 437 pages; `palabras.pagina` goes
up to 436, the last page with entries.

### Rows complete and flags left

- 2,371 of 2,419 rows (98.0 %) have a category, a definition, a movement description and an image,
  and no review flag.
- The 48 flagged rows are fields the PDF never prints, mostly the 34 province entries (43 rows have
  no definition and 5 more are flagged for another reason). They stay flagged instead of receiving
  invented text. Second signs of a headword keep "SEÑA NUMERO DOS" as their definition because
  that is what is printed; 20 definitions copied from a neighbour were dropped, and APLAUDIR is
  flagged instead of borrowing the definition of APLAUSO.
- 37 rows stay in `Sin Categoría` because the PDF prints no category for them.

### Reachability from natural Spanish

The A-Z reach audits (`dict_reach`, one per alphabet range) generated inflections, feminine and
plural forms, conjugations, reflexive forms and Dominican variants for each headword and ran them
through the translator. A form is reachable when it resolves to the sign of its own entry. The
"reachable before" column is the audit on 2.2.0. The "reachable after" column re-runs the 685 forms
that failed on 2.3.0 (synonym merge plus the generic morphology rules); forms that already passed
were checked for regressions with a before/after diff of the lemmatizer, not re-counted.

| Range | Forms tested | Unreachable before | Fixed in 2.3.0 | Still unreachable | Reachable before | Reachable after |
|---|---|---|---|---|---|---|
| A-C | 2,375 | 189 | 117 | 72 | 0.920 | 0.970 |
| D-F | 1,336 | 91 | 41 | 50 | 0.932 | 0.963 |
| G-L | 1,260 | 86 | 66 | 20 | 0.932 | 0.984 |
| M-O | 797 | 66 | 36 | 30 | 0.917 | 0.962 |
| P-R | 1,595 | 135 | 100 | 35 | 0.915 | 0.978 |
| S-Z | 1,310 | 118 | 38 | 80 | 0.910 | 0.939 |
| Total | 8,673 | 685 | 398 | 287 | 0.921 | 0.967 |

The 287 forms still unreachable are mostly verb and noun pairs that need sentence context (ABORTAR
and ABORTO, CUENTA), words with a tilde on the n, stopwords the engine drops, and headwords with a
qualifier in parentheses. Words that have no entry in the PDF were handled separately: 1,297
single-word synonyms were added to `data/synonyms_extra.json` (now 2,271 entries, all
`curated-pending-review`) and 106 multi-word proposals wait in `data/synonyms_phrases_pending.json`
until a database owner adds them to `sinonimos_mapeo`. 177 proposals were rejected for conflicts,
a tilde mismatch, meaning shifts or inflections of another headword.

### Effect on the evaluation

| Corpus | Measure | 2.2.0 | 2.3.0 |
|---|---|---|---|
| Gold (134 sentences) | lexical coverage | 0.9146 | 0.9146 |
| Gold | lemma recall | 0.9747 | 0.9747 |
| Gold | lemma precision | 0.9655 | 0.9565 |
| Realistic (42 paragraphs) | lexical coverage | 0.7562 | 0.7799 |
| Realistic | common-word fingerspelling | 0.2303 | 0.2057 |

## Known data issues left

- 43 rows have no definition and 5 more rows are flagged for review (48 in total): the PDF prints
  nothing for those fields. They need an interpreter or a second edition of the dictionary.
- 37 rows have no category for the same reason.
- `tools/recover_dictionary_entries.py` reports the 8 line fragments above as missing. They are
  already merged rows, so do not apply them.
- The database ids are no longer contiguous (`lsrd_0001` to `lsrd_2476` with gaps where split
  headwords were merged). Letter ids and all other ids that remain were kept.

## Re-running

```sh
uv run tools/recover_dictionary_entries.py --pdf <dictionary.pdf> --db lsrd_dictionary.db \
    --images extracted_images             # report only
uv run tools/recover_dictionary_entries.py --pdf <dictionary.pdf> --db lsrd_dictionary.db \
    --images extracted_images --apply --backup <backup.db>
python tools/find_dictionary_gaps.py      # remaining frequent-word gaps (stdout)
```
