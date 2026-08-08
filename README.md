# Dominican Sign Language (LSRD) Translation Model

> **Biblionx-Project** — thesis project (Trabajo de Grado, UNICDA). This is the active, working repository: everything else in the [Biblionx-Project](https://github.com/Biblionx-Project) organization is either upstream VLibras reference code or supporting tooling.

## 📌 Overview

This repository contains a self-contained, portable implementation of the **Spanish-to-Dominican-Sign-Language (LSRD) translation engine**, plus the REST API and browser extension that expose it as a working product.

It's designed as an **exportable, standalone package**: the SQLite relational database (`lsrd_dictionary.db`), all 2,458 cropped vector sign illustrations (`extracted_images/`), the Natural Language Processing (NLP) engine, and interactive test scripts are all included.

Any developer, instructor, or researcher can copy this directory to another machine and start querying or translating immediately — **no external dependencies required** for the core CLI (standard library only).

Note: the translation pipeline itself works on **Spanish input text** (that's the language it's built to parse) and outputs LSRD sign sequences. That's a functional requirement, not a language choice for this README.

---

## 📦 Package Contents

| File / Folder | Description |
| :--- | :--- |
| **`lsrd_dictionary.db`** | SQLite3 database with 2,458 lemmas, grammatical categories, movement descriptions, and references to the official PDF. |
| **`extracted_images/`** | 2,458 cropped vector sign images in PNG format (`lsrd_0001.png` through `lsrd_2458.png`). |
| **`main.py`** | Interactive console (CLI) — type a Spanish sentence and see the ordered LSRD translation. |
| **`nlp_engine.py`** | NLP module: normalization, stopword filtering, verb lemmatization, and syntactic reordering. |
| **`translator.py`** | Relational sign mapper with synonym resolution and A-Z fingerspelling fallback. |
| **`backend_api/`** | Standalone HTTP REST API (Python `http.server`, no external deps) that the browser extension talks to. Ships with its own copy of the DB and images so it runs independently. |
| **`browser_extension/`** | Manifest V3 browser extension: select text on any page, get an accessible LSRD sign player overlay. |
| **`README.md`** | This file. |

---

## 🏗️ Architecture

The model translates Spanish sentences to LSRD through a structured 3-stage pipeline:

```
[Input Spanish text] (e.g. "El abogado no trabaja hoy en la escuela")
       │
       ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 1. NLP Preprocessing Module (nlp_engine.py)                                 │
 │    - Tokenization and lowercase/accent normalization                       │
 │    - Stopword and article filtering (words with no direct sign equivalent) │
 │    - Verb lemmatization (e.g. "trabajaba" -> "trabajar")                    │
 │    - LSRD syntactic reordering: [TIME] + [PLACE] + [SUBJECT] + [VERB] + [NEGATION] │
 └───────────────────────────────────┬─────────────────────────────────────────┘
                                     │ (LSRD grammatical sequence)
                                     ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 2. Local Database Mapper (translator.py & lsrd_dictionary.db)               │
 │    - SQLite lookup by word or synonym against the 'palabras' table          │
 │    - Extracts cheremic parameters (handshape, orientation, movement)        │
 │    - A-Z fingerspelling fallback: if a word or proper noun isn't found,     │
 │      it's substituted with the fingerspelling alphabet sign sequence.       │
 └───────────────────────────────────┬─────────────────────────────────────────┘
                                     │
                                     ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 3. Output Sequence (main.py / backend_api/server.py)                        │
 │    - Ordered list of signs with their DB ID (`lsrd_XXXX`)                    │
 │    - Cheremic (Stokoe) movement description                                 │
 │    - Page number in the Official LSRD Dictionary                            │
 │    - Local path to the vector illustration (`extracted_images/lsrd_XXXX.png`)│
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start — CLI

Requires **Python 3.6+** only (standard library, **no `pip install` needed**):

1. Open a terminal in this directory:
   ```bash
   cd biblionx-lsrd-translator
   ```

2. Run the interactive console:
   ```bash
   python3 main.py
   ```

3. Type any sentence in Spanish.

### Example terminal output:
```text
======================================================================
      BIBLIONX - DOMINICAN SIGN LANGUAGE (LSRD) TRANSLATION ENGINE
======================================================================
Type a sentence in Spanish to translate it to LSRD (or type 'exit'):

Spanish > El abogado no trabaja hoy en la escuela

--- LSRD TRANSLATION RESULT ---
Original sentence:     "El abogado no trabaja hoy en la escuela"
Grammatical sequence:  ['hoy', 'escuela', 'abogado', 'trabajar', 'no']
Total signs:           5

ORDERED SIGN SEQUENCE:
  01. HOY                  (Lexical sign)       | Page 210
      - Movement: Las manos en forma de Y con las palmas hacia arriba bajan simultáneamente en rectas paralelas.
      - Image:    extracted_images/lsrd_1146.png

  02. ESCUELA              (Lexical sign)       | Page 167
      - Movement: Las manos planas con las palmas enfrentadas; la mano dominante arriba con los dedos hacia afuera sobre la otra mano...
      - Image:    extracted_images/lsrd_0908.png

  03. ABOGADO,DA           (Lexical sign)       | Page 30
      - Movement: La mano dominante en forma de L toca arriba y abajo la mano plana contraria.
      - Image:    extracted_images/lsrd_0009.png

  04. TRABAJAR             (Lexical sign)       | Page 376
      - Movement: Laborar, realizar una actividad que supone esfuerzo...
      - Image:    extracted_images/lsrd_2124.png

  05. NO                   (Lexical sign)       | Page 272
      - Movement: La mano en forma de 3 cerrado con la palma hacia afuera, une los dedos mayor, índice y pulgar...
      - Image:    extracted_images/lsrd_1503.png
```

*(Movement descriptions come straight from the Official LSRD Dictionary and are kept in their original Spanish — they're primary-source data, not UI text.)*

---

## 🌐 REST API + Browser Extension

`backend_api/` and `browser_extension/` together are the actual product: select text on any web page, get it translated to LSRD with a visual sign player.

### Run the API server
```bash
cd backend_api
python3 server.py
```
Starts an HTTP server on `http://127.0.0.1:8000` with:
- `POST /api/v1/translate` — body `{"texto": "..."}`, returns the NLP analysis and ordered sign sequence.
- `GET /api/v1/words/{lemma}` — direct dictionary lookup.
- `GET /extracted_images/{id}.png` — serves the sign images.

### Load the browser extension
1. Go to `chrome://extensions` (or your browser's equivalent), enable Developer Mode.
2. "Load unpacked" → select the `browser_extension/` folder.
3. With the API server running, select any text on a page — a floating "Translate to LSRD" button appears, opening an accessible sign player overlay (play/pause/prev/next, adjustable speed 0.75x–2.0x).

---

## 🗄️ Developer Guide: Querying `lsrd_dictionary.db` Directly

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

## Known limitations

- The lemmatizer covers ~35 common irregular Spanish verbs (explicit whitelist) plus a dictionary-driven generator for regular `-ar/-er/-ir` verbs already present in `lsrd_dictionary.db`. Verbs outside that coverage fall back to fingerspelling.
- 63 of 2,458 dictionary entries (2.6%) are flagged for manual review; a handful of basic words (e.g. some common adjectives) are known gaps from the PDF extraction pass.
