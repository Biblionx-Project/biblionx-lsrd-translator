"""Export CSV review sheets for LSRD interpreters and Deaf reviewers.

The sheets are meant for a Spanish-speaking (Dominican) audience, so column
headers and instructions are in Spanish. Output goes to docs/validation/ as
UTF-8 with BOM so Excel opens accents and the letter n-tilde correctly.

Sheets
  00_instrucciones.csv          how to fill in the sheets
  01_sinonimos_curados.csv      data/synonyms_extra.json (word -> target sign)
  02_lexico_dominicano.csv      data/dominican_lexicon.json (dominicanismos)
  03_reglas_gramatica.csv       30 sentences run through the full pipeline
  04_coincidencias_difusas.csv  sample of fuzzy (approximate) matches

Everything is deterministic: running it twice yields identical files. The AI
fallback is disabled for the run so the pipeline output never depends on a
provider. Reviewer columns are left empty on purpose.

Usage:
    python tools/export_review_sheets.py
    python tools/export_review_sheets.py --out-dir somewhere --delimiter ";"
"""
import argparse
import csv
import json
import os
import random
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# Deterministic run: never call an AI provider while exporting.
os.environ["BIBLIONX_LLM_PROVIDER"] = ""

from ml_matcher import normalize  # noqa: E402
from nlp_engine import LSRDNlpEngine, load_synonyms_extra  # noqa: E402
from translator import LSRDTranslator, DB_PATH, FUZZY_MIN_SCORE  # noqa: E402
import find_dictionary_gaps  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "docs", "validation")
LEXICON_PATH = os.path.join(ROOT, "data", "dominican_lexicon.json")

REVIEW_OK = "correcto (si/no)"
REVIEW_SIGN = "seña sugerida"
REVIEW_NOTES = "comentarios"

INSTRUCTIONS = [
    "INSTRUCCIONES PARA REVISORES (intérpretes de LSRD y personas sordas)",
    "",
    "Gracias por ayudar a validar el traductor Biblionx. Su revisión decide qué datos se corrigen.",
    "",
    "1. Abra cada hoja CSV con Excel o LibreOffice (codificación UTF-8). Si las columnas aparecen pegadas en una sola, use Datos > Texto en columnas con separador coma.",
    "2. No cambie las columnas que ya vienen llenas. Solo escriba en las columnas de revisión del final de cada hoja.",
    "3. Escriba si o no en la columna 'correcto (si/no)'. Si responde no, escriba la seña o el orden correcto en 'seña sugerida' (o 'orden sugerido' en la hoja de gramática).",
    "4. Use 'comentarios' para variantes regionales, diferencias entre generaciones o dudas. Deje en blanco lo que no pueda juzgar; no adivine.",
    "5. Guarde el archivo como CSV UTF-8 (delimitado por comas) y devuélvalo con su nombre o iniciales en el nombre del archivo.",
    "",
    "HOJAS",
    "01_sinonimos_curados: una palabra del español que el sistema trata como equivalente de otra seña. Pregunta: ¿esa palabra se puede representar con la seña destino?",
    "02_lexico_dominicano: formas dominicanas (pa', toy, guagua...) y el equivalente estándar al que se convierten antes de buscar la seña. Pregunta: ¿el equivalente es correcto y la seña resultante es la que usted usaría?",
    "03_reglas_gramatica: oraciones en español con el orden de señas que produce el sistema. Pregunta: ¿ese orden es natural en LSRD? Si no, escriba el orden correcto.",
    "04_coincidencias_difusas: palabras que no están en el diccionario y que el sistema relaciona con la palabra más parecida. Pregunta: ¿la palabra elegida tiene el mismo significado? Es la hoja más importante: una coincidencia incorrecta muestra una seña equivocada sin aviso.",
    "",
    "Estas hojas no contienen información personal; no escriba datos personales en los comentarios.",
]


def safe(value):
    """Neutralise spreadsheet formulas and flatten None."""
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "@") or (text[:1] == "-" and len(text) > 1 and not text[1].isspace()):
        return "'" + text
    return text


def write_csv(path, header, rows, delimiter=","):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([safe(v) for v in row])
    return len(rows)


def db_row(conn, palabra_id):
    row = conn.execute(
        "SELECT p.palabra_es, p.palabra_norm, p.pagina, "
        "COALESCE((SELECT descripcion_sena FROM senas_descripciones d WHERE d.palabra_id = p.id LIMIT 1), '') "
        "FROM palabras p WHERE p.id = ?", (palabra_id,)).fetchone()
    return row or ("", "", "", "")


def gloss(translator, sequence):
    """Readable gloss: whole words as WORD, fingerspelled words as D-E-F."""
    parts, letters = [], []
    for item in sequence:
        if item.get("es_deletreo"):
            letters.append(item.get("letra") or "")
            continue
        if letters:
            parts.append("-".join(letters))
            letters = []
        parts.append(item["palabra_es"])
    if letters:
        parts.append("-".join(letters))
    return " ".join(parts)


def methods(sequence):
    out = []
    for item in sequence:
        if item.get("es_deletreo"):
            if not out or out[-1] != "deletreo":
                out.append("deletreo")
        else:
            out.append(item.get("match_method", ""))
    return " ".join(out)


# ---------------------------------------------------------------- sheet 1
def sheet_synonyms(conn):
    header = ["palabra", "seña_destino", "palabra_es (diccionario)", "pagina",
              "descripcion_sena", "palabra_id", REVIEW_OK, REVIEW_SIGN, REVIEW_NOTES]
    rows = []
    for entry in sorted(load_synonyms_extra(), key=lambda e: (e["target_norm"], e["word"])):
        palabra_es, _norm, page, desc = db_row(conn, entry.get("palabra_id"))
        rows.append([entry["word"], entry.get("target_norm", ""), palabra_es, page, desc,
                     entry.get("palabra_id", ""), "", "", ""])
    return header, rows


# ---------------------------------------------------------------- sheet 2
def sheet_lexicon(translator, nlp):
    with open(LEXICON_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    header = ["tipo", "forma_dominicana", "equivalente_estandar", "señas_resultantes",
              REVIEW_OK, REVIEW_SIGN, REVIEW_NOTES]
    kinds = [("ortografico (pronunciación escrita)", "orthographic"),
             ("lexico (palabra dominicana)", "lexical")]
    rows = []
    for label, key in kinds:
        for form, standard in sorted(data.get(key, {}).items()):
            result = nlp.process(form)
            seq = translator.translate_sequence(result["secuencia_lsrd"])
            rows.append([label, form, standard, gloss(translator, seq), "", "", ""])
    return header, rows


# ---------------------------------------------------------------- sheet 3
GRAMMAR_SENTENCES = [
    ("tiempo primero", "Ayer comí arroz con pollo."),
    ("tiempo primero", "Mañana voy a la escuela."),
    ("tiempo primero", "Hoy mi mamá trabaja en el hospital."),
    ("tiempo primero", "El lunes estudio con mi hermano."),
    ("tiempo primero", "Ahora quiero agua."),
    ("tiempo primero", "Anoche mi papá llegó tarde."),
    ("negación al final", "No quiero comer."),
    ("negación al final", "Yo no tengo dinero."),
    ("negación al final", "Mi hermano nunca estudia."),
    ("negación al final", "No me gusta la leche."),
    ("negación al final", "Ayer no fui a la escuela."),
    ("negación al final", "Mañana no trabajo."),
    ("pregunta con palabra interrogativa al final", "¿Cómo te llamas?"),
    ("pregunta con palabra interrogativa al final", "¿Dónde vives?"),
    ("pregunta con palabra interrogativa al final", "¿Qué quieres comer?"),
    ("pregunta con palabra interrogativa al final", "¿Cuándo llega tu papá?"),
    ("pregunta con palabra interrogativa al final", "¿Quién es tu maestro?"),
    ("pregunta con palabra interrogativa al final", "¿Por qué no estudias?"),
    ("pregunta si/no", "¿Tienes hambre?"),
    ("pregunta si/no", "¿Quieres agua?"),
    ("oración simple", "La niña lee un libro."),
    ("oración simple", "Mi familia vive en Santo Domingo."),
    ("oración simple", "El doctor trabaja en el hospital."),
    ("cantidad con sustantivo", "Tengo dos hermanos."),
    ("cantidad con sustantivo", "Necesito diez libros."),
    ("varias cláusulas", "Ayer llovió, hoy no salgo."),
    ("varias cláusulas", "Mi mamá cocina y mi papá trabaja."),
    ("dominicanismo", "Toy cansao, pa' la casa voy."),
    ("dominicanismo", "Vamo a tomar la guagua."),
    ("dominicanismo", "Ahorita voy al colmado."),
]


def sheet_grammar(translator, nlp):
    header = ["id", "regla", "oracion_es", "orden_lsrd_sistema", "señas_resultantes",
              "metodo_por_seña", "orden correcto (si/no)", "orden sugerido", REVIEW_NOTES]
    rows = []
    for i, (rule, sentence) in enumerate(GRAMMAR_SENTENCES, 1):
        result = nlp.process(sentence)
        seq = translator.translate_sequence(result["secuencia_lsrd"])
        rows.append([f"G{i:02d}", rule, sentence, " ".join(result["secuencia_lsrd"]).upper(),
                     gloss(translator, seq), methods(seq), "", "", ""])
    return header, rows


# ---------------------------------------------------------------- sheet 4
FUZZY_NEAR_MISS_MIN = 0.70
TYPO_SAMPLE = 45
SEED = 20240611


def _typo(word, rnd):
    """One deterministic keyboard-style error: delete, duplicate or swap."""
    pos = rnd.randrange(1, len(word) - 1)
    kind = rnd.choice(("borrar", "duplicar", "intercambiar"))
    if kind == "borrar":
        return word[:pos] + word[pos + 1:], kind
    if kind == "duplicar":
        return word[:pos] + word[pos] + word[pos:], kind
    return word[:pos] + word[pos + 1] + word[pos] + word[pos + 2:], kind


def sheet_fuzzy(translator, conn):
    fuzzy = translator._index.fuzzy
    exact = translator._index.exact
    header = ["palabra_entrada", "origen", "coincidencia", "palabra_es (diccionario)", "pagina",
              "puntuacion", "resultado_sistema", REVIEW_OK, REVIEW_SIGN, REVIEW_NOTES]
    candidates = []

    # 1) typos of dictionary words (seeded, reproducible)
    rnd = random.Random(SEED)
    pool = sorted(w for w in exact if w.isalpha() and 6 <= len(w) <= 12)
    for word in rnd.sample(pool, TYPO_SAMPLE):
        typo, kind = _typo(word, rnd)
        if typo not in exact:
            candidates.append((typo, f"error de escritura ({kind}) de '{word}'"))

    # 2) frequent words that the dictionary lacks: what would fuzzy do with them?
    gaps, _total, _med = find_dictionary_gaps.find_gaps(DB_PATH)
    for gap in gaps:
        candidates.append((gap["norm"], "palabra frecuente sin entrada"))

    rows = []
    for word, origin in candidates:
        norm = normalize(word)
        top = fuzzy.candidates(norm, k=1)
        if not top:
            continue
        best = top[0]
        if best["score"] >= FUZZY_MIN_SCORE:
            verdict = "se usa esta seña"
        elif best["score"] >= FUZZY_NEAR_MISS_MIN:
            verdict = "descartada (se deletrea)"
        else:
            continue
        palabra_es, _n, page, _d = db_row(conn, best["palabra_id"])
        rows.append([word, origin, best["norm"], palabra_es, page, f"{best['score']:.2f}",
                     verdict, "", "", ""])
    rows.sort(key=lambda r: (r[6] != "se usa esta seña", -float(r[5]), r[0]))
    return header, rows


# ---------------------------------------------------------------- main
def export(out_dir=DEFAULT_OUT, delimiter=","):
    os.makedirs(out_dir, exist_ok=True)
    translator = LSRDTranslator(DB_PATH)
    nlp = LSRDNlpEngine(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        sheets = [
            ("01_sinonimos_curados.csv", sheet_synonyms(conn)),
            ("02_lexico_dominicano.csv", sheet_lexicon(translator, nlp)),
            ("03_reglas_gramatica.csv", sheet_grammar(translator, nlp)),
            ("04_coincidencias_difusas.csv", sheet_fuzzy(translator, conn)),
        ]
    finally:
        conn.close()
    write_csv(os.path.join(out_dir, "00_instrucciones.csv"), ["Instrucciones"],
              [[line] for line in INSTRUCTIONS], delimiter)
    counts = {}
    for name, (header, rows) in sheets:
        counts[name] = write_csv(os.path.join(out_dir, name), header, rows, delimiter)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--delimiter", default=",", help="use ';' for Excel with Spanish (Spain) regional settings")
    args = ap.parse_args()
    for name, n in export(args.out_dir, args.delimiter).items():
        print(f"{name}: {n} rows")


if __name__ == "__main__":
    main()
