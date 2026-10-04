"""Find frequent Spanish content words that have no sign in the dictionary.

The word list below (~400 high-frequency Spanish content words, written by
hand, accents kept for readability) is checked against everything the live
pipeline can resolve without guessing: exact entries, DB synonyms, curated
synonyms (data/synonyms_extra.json) and morphology (plural, gender, verb
conjugation). Words that still resolve to nothing are "gaps".

For every gap the script estimates the page of the official LSRD dictionary
from its alphabetical neighbours (e.g. COMER sits between COMENZAR p.113 and
COMERCIO p.113 -> p.113) and classifies the gap:

  * extraction_miss : neighbours share (or nearly share) a page whose entry
                      count is below normal -> the word is probably printed
                      there and the extraction skipped it. Re-extract.
  * check_page      : neighbours share a page with normal density, or the
                      page span is 2-3 pages. Look at the page, may be absent.
  * no_entry        : abstract/adverbial word that sign dictionaries usually
                      omit, or the neighbour span is too wide to be reliable.

The classification is a heuristic to prioritise human work, not a verdict.

Usage:
    python tools/find_dictionary_gaps.py                  # print the table
    python tools/find_dictionary_gaps.py --out docs/DICTIONARY_GAPS.md
"""
import argparse
import bisect
import os
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml_matcher import normalize  # noqa: E402
from nlp_engine import get_resources  # noqa: E402
import morphology  # noqa: E402
from translator import LSRDTranslator, DB_PATH  # noqa: E402

# Groups: verbo, sustantivo, adjetivo, adverbio.
FREQUENT_WORDS = {
    "verbo": """
abrir acabar aceptar acompañar actuar agradecer ayudar bailar beber buscar caer cambiar
caminar cantar cerrar cocinar comenzar comer comprar comprender conocer construir contar
contestar correr crear creer cuidar dar deber decidir decir dejar descansar desear despertar
dibujar dormir ejercitar empezar encontrar enseñar entender entrar enviar escribir escuchar
esperar estudiar existir explicar faltar ganar gustar haber hablar hacer imaginar importar
invitar ir jugar lavar leer levantar limpiar llamar llegar llevar llorar mandar mirar morir
mostrar mover nacer necesitar notar obtener ofrecer olvidar oír pagar parecer partir pasar
pedir pensar perder permitir pintar poder poner preguntar preparar presentar probar prometer
proteger quedar querer recibir recordar reír repetir resolver responder reunir saber sacar
salir seguir sentar sentir ser servir subir tener terminar tocar tomar trabajar traer usar
vender venir ver viajar visitar vivir volver
""",
    "sustantivo": """
abuela abuelo agua aire alegría alimento amigo amor animal año árbol arroz arte azúcar
bandera barrio bebé boca brazo cabeza café calle cama cara carne carta cena centro cielo
ciudad clase cocina color comida compañero computadora comunidad conversación corazón cosa
cuerpo cumpleaños dedo derecho desayuno día dinero doctor dolor domingo dueño edad ejemplo
empresa enfermedad equipo escuela espejo esposa esposo estudiante familia fiesta flor fruta
fuego futuro gente gobierno hambre hermana hermano hija hijo historia hogar hombre hora
hospital hotel idea iglesia importancia información invierno isla jardín joven juego jueves
lápiz lengua libro luna lunes madre maestro mano mañana mar martes médico mes mesa miedo
momento mujer mundo música nada navidad niña niño noche nombre noticia número ojo oreja
padre país palabra papel pareja parque pelo película persona pie pierna plato playa pueblo
puerta pregunta problema profesor programa pájaro rato razón regalo respuesta rey
río ropa sábado salud sangre semana señal señor señora sol sombra sonido sopa sueño suerte
tarde teléfono televisión tiempo tierra tío tía trabajo tren universidad vecino
ventana verdad vida viento viernes viaje voz zapato
""",
    "adjetivo": """
alegre alto amable amarillo antiguo azul bajo barato blanco bonito bueno caliente cansado
cercano claro contento corto cuidadoso débil delgado difícil diferente dulce enfermo
enorme especial estrecho fácil famoso feliz feo flaco frío fuerte gordo grande gris
gracioso hermoso importante inteligente largo libre limpio listo lleno malo mojado
moreno necesario negro nervioso nuevo oscuro pequeño peligroso pobre posible rápido rico
rojo rubio sano seco sencillo simple sucio tranquilo triste último útil vacío verde viejo
""",
    "adverbio": """
además ahora allí aquí después siempre nunca también todavía tampoco ayer hoy
temprano cerca lejos adelante atrás arriba abajo dentro fuera bastante demasiado
mucho poco casi entonces luego antes mientras quizás realmente generalmente finalmente
rápidamente lentamente claramente especialmente
""",
}

# Abstract / adverbial words that sign dictionaries commonly omit.
LIKELY_NO_ENTRY = {
    "además", "también", "tampoco", "todavía", "bastante", "demasiado", "casi",
    "entonces", "luego", "mientras", "quizás", "realmente", "generalmente",
    "finalmente", "rápidamente", "lentamente", "claramente", "especialmente",
    "haber", "deber", "existir", "parecer", "importar", "nada", "dentro", "fuera",
}

WIDE_SPAN = 3  # pages; wider than this the estimate is not reliable


def load_words():
    seen, out = set(), []
    for group, block in FREQUENT_WORDS.items():
        for w in block.split():
            n = normalize(w)
            if n not in seen:
                seen.add(n)
                out.append((w, n, group))
    return out


def resolves(translator, known, norm):
    """True when the live pipeline reaches a dictionary sign without fuzzy guessing."""
    pid, _ = translator._lookup_id(norm)
    if pid:
        return True
    lemma, _how = morphology.lemmatize(norm, known)
    if lemma != norm:
        pid, _ = translator._lookup_id(lemma)
        return bool(pid)
    return False


def build_page_index(db_path):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT palabra_norm, palabra_es, pagina FROM palabras").fetchall()
    finally:
        conn.close()
    rows = [(n, e, p) for n, e, p in rows if n]
    rows.sort()
    norms = [r[0] for r in rows]
    per_page = Counter(r[2] for r in rows)
    return rows, norms, per_page


def estimate(norm, rows, norms):
    """(pred_row, succ_row, lo_page, hi_page) from alphabetical neighbours."""
    i = bisect.bisect_left(norms, norm)
    pred = rows[i - 1] if i > 0 else None
    succ = rows[i] if i < len(rows) else None
    pages = [r[2] for r in (pred, succ) if r]
    return pred, succ, min(pages), max(pages)


def classify(word, group, lo, hi, per_page, median_density):
    if word in LIKELY_NO_ENTRY or (group == "adverbio" and word.endswith("mente")):
        return "no_entry"
    span = hi - lo
    if span > WIDE_SPAN:
        return "no_entry"
    pages = range(lo, hi + 1)
    density = sum(per_page.get(p, 0) for p in pages) / len(pages)
    if span <= 1 and density < median_density:
        return "extraction_miss"
    return "check_page"


LABEL = {
    "extraction_miss": "probable extraction miss",
    "check_page": "check page",
    "no_entry": "probably no entry",
}


def find_gaps(db_path=DB_PATH):
    translator = LSRDTranslator(db_path)
    known = get_resources(db_path).known
    rows, norms, per_page = build_page_index(db_path)
    median_density = statistics.median(per_page.values())
    fuzzy = translator._index.fuzzy
    words = load_words()
    gaps = []
    for word, norm, group in words:
        if resolves(translator, known, norm):
            continue
        pred, succ, lo, hi = estimate(norm, rows, norms)
        hit = fuzzy.match(norm, 0.84)
        gaps.append({
            "word": word, "norm": norm, "group": group,
            "pred": pred, "succ": succ, "lo": lo, "hi": hi,
            "status": classify(word, group, lo, hi, per_page, median_density),
            "fuzzy": hit["norm"] if hit else "",
        })
    gaps.sort(key=lambda g: (g["lo"], g["norm"]))
    return gaps, len(words), median_density


def page_text(g):
    return f"p.{g['lo']}" if g["lo"] == g["hi"] else f"p.{g['lo']}-{g['hi']}"


def neighbour_text(r):
    return f"{r[1]} p.{r[2]}" if r else "-"


def render_markdown(gaps, total, median_density):
    counts = Counter(g["status"] for g in gaps)
    pages = defaultdict(list)
    for g in gaps:
        if g["status"] != "no_entry":
            for p in range(g["lo"], g["hi"] + 1):
                pages[p].append(g["word"].upper())
    lines = [
        "# Dictionary gaps (frequent words without a sign)",
        "",
        "Generated by `python tools/find_dictionary_gaps.py --out docs/DICTIONARY_GAPS.md`. "
        "Do not edit by hand; re-run after changing the database or `data/synonyms_extra.json`.",
        "",
        f"Checked {total} high-frequency Spanish content words (list inside the script). "
        f"**{len(gaps)}** do not resolve to a sign through exact match, synonyms, curated "
        "synonyms or morphology.",
        "",
        "| Class | Meaning | Count |",
        "|---|---|---|",
        f"| probable extraction miss | neighbours share a page with fewer entries than usual (median {median_density:g}/page): the word is probably printed there and was skipped | {counts['extraction_miss']} |",
        f"| check page | page estimate is narrow but the page looks complete, or the span is 2-3 pages | {counts['check_page']} |",
        f"| probably no entry | abstract/adverbial word, or the neighbour span is too wide | {counts['no_entry']} |",
        "",
        "The page is estimated from the alphabetical neighbours in the database "
        "(COMER sits between COMENZAR p.113 and COMERCIO p.113, so p.113). "
        "It is a hint for re-extraction, not proof that the printed dictionary "
        "contains the word.",
        "",
        "## Pages to re-extract first",
        "",
        "| Page | Candidate words |",
        "|---|---|",
    ]
    for p in sorted(pages):
        lines.append(f"| {p} | {', '.join(sorted(set(pages[p])))} |")
    lines += [
        "",
        "## All gaps",
        "",
        "| Word | Type | Estimated page | Previous entry | Next entry | Class | Fuzzy would pick |",
        "|---|---|---|---|---|---|---|",
    ]
    for g in gaps:
        lines.append(
            f"| {g['word'].upper()} | {g['group']} | {page_text(g)} | {neighbour_text(g['pred'])} "
            f"| {neighbour_text(g['succ'])} | {LABEL[g['status']]} | {g['fuzzy'] or '-'} |")
    lines += [
        "",
        "`Fuzzy would pick` is the dictionary word the fuzzy matcher (threshold 0.84) would "
        "silently substitute today. A non-empty value that is not a real equivalent is a "
        "correctness risk until the real entry is added.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", help="write the Markdown report here instead of stdout")
    args = ap.parse_args()
    gaps, total, med = find_gaps(args.db)
    text = render_markdown(gaps, total, med)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"{len(gaps)} gaps of {total} words -> {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
