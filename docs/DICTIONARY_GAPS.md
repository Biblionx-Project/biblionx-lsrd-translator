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
   Another 42 headwords are already in the database as several rows each. The original
   extraction split them by printed line, for example `PERAVIA` + `(BANÍ)`. Those rows were
   left as they are because existing ids must not change.
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

## Known data issues left unchanged

- 42 headwords are stored as several rows, one per printed line or parenthesis (for example
  `BATERÍA` + `(INSTRUMENTO`, and the province names on pages 430-436). Merging them would
  change existing ids.
- 256 rows from the original extraction have no movement description. They include entries
  that share one description with the next headword (only the last one received it, for
  example DIBUJAR / DIBUJO), alphabet letters and part of the regional-signs section.
  `tests/test_dictionary_recovery.py` checks that this number does not grow.

## Re-running

```sh
uv run tools/recover_dictionary_entries.py --pdf <dictionary.pdf> --db lsrd_dictionary.db \
    --images extracted_images             # report only
uv run tools/recover_dictionary_entries.py --pdf <dictionary.pdf> --db lsrd_dictionary.db \
    --images extracted_images --apply --backup <backup.db>
python tools/find_dictionary_gaps.py      # remaining frequent-word gaps (stdout)
```
