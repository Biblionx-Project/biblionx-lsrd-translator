"""Dominican Spanish normalization layer.

Rewrites Dominican orthography/colloquialisms into standard Spanish BEFORE the
NLP stage, so the dictionary lookup can match them. Mappings live in
data/dominican_lexicon.json:

  orthographic: spelling variants (pa' -> para, toy -> estoy, cansao -> cansado)
  lexical:      Dominicanisms -> standard word, only where that standard word
                exists in lsrd_dictionary.db (see verify_lexical).

Stdlib only; the JSON is loaded once and cached.
"""
import json
import os
import re
import sqlite3
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
LEXICON_PATH = os.path.join(_HERE, "data", "dominican_lexicon.json")
DB_PATH = os.path.join(_HERE, "lsrd_dictionary.db")

# Word chars plus inner/trailing apostrophes (pa', to', pa'l).
_TOKEN_RE = re.compile(r"\w+(?:['\u2019]\w+)*['\u2019]?")
_cache = None


def _fold(s):
    """Lowercase, straighten apostrophes, strip accents."""
    s = s.lower().replace("\u2019", "'")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def load_lexicon(path=LEXICON_PATH):
    """Return the merged token->replacement map (cached for the default path)."""
    global _cache
    if _cache is not None and path == LEXICON_PATH:
        return _cache
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    merged = {}
    for section in ("orthographic", "lexical"):
        for k, v in (data.get(section) or {}).items():
            merged[_fold(k)] = v
    if path == LEXICON_PATH:
        _cache = merged
    return merged


def _match_case(src, repl):
    if len(src) > 1 and src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def normalize_text(text):
    """Replace Dominican variants token by token; punctuation is untouched."""
    if not text:
        return text
    lex = load_lexicon()
    if not lex:
        return text

    matches = list(_TOKEN_RE.finditer(text))
    if not matches:
        return text

    max_phrase_len = max((len(k.split()) for k in lex if ' ' in k), default=1)
    i = 0
    n = len(matches)
    replacements = []

    while i < n:
        matched_phrase = False
        if max_phrase_len > 1:
            for size in range(min(max_phrase_len, n - i), 1, -1):
                span_valid = True
                for j in range(i, i + size - 1):
                    between = text[matches[j].end():matches[j + 1].start()]
                    if not between or not between.isspace():
                        span_valid = False
                        break
                if not span_valid:
                    continue

                phrase_key = " ".join(_fold(matches[j].group(0)) for j in range(i, i + size))
                repl = lex.get(phrase_key)
                if repl is not None:
                    span_start = matches[i].start()
                    span_end = matches[i + size - 1].end()
                    orig_span = text[span_start:span_end]
                    replacements.append((span_start, span_end, _match_case(orig_span, repl)))
                    i += size
                    matched_phrase = True
                    break

        if not matched_phrase:
            m = matches[i]
            tok = m.group(0)
            key = _fold(tok)
            repl = lex.get(key)
            if repl is None and "'" in key:
                repl = lex.get(key.strip("'"))
            if repl is not None:
                replacements.append((m.start(), m.end(), _match_case(tok, repl)))
            i += 1

    if not replacements:
        return text

    result = list(text)
    for start, end, repl in reversed(replacements):
        result[start:end] = list(repl)
    return "".join(result)


def verify_lexical(db_path=DB_PATH, path=LEXICON_PATH):
    """Return lexical targets absent from the DB (empty list means all valid)."""
    with open(path, encoding="utf-8") as f:
        lexical = json.load(f).get("lexical", {})
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        missing = []
        for src, dst in lexical.items():
            d = _fold(dst)
            row = con.execute(
                "SELECT 1 FROM palabras WHERE palabra_norm=? OR palabra_norm LIKE ? LIMIT 1",
                (d, d + ",%")).fetchone()
            if not row:
                missing.append((src, dst))
        return missing
    finally:
        con.close()


if __name__ == "__main__":
    assert normalize_text("Pa' que quieres eso") == "Para que quieres eso"
    assert normalize_text("yo toy cansao") == "yo estoy cansado"
    assert normalize_text("Ta bien, tamo listos.") == "Esta bien, estamos listos."
    assert normalize_text("tu ere mi amigo") == "tu eres mi amigo"
    assert normalize_text("to' el dia, na' mas") == "todo el dia, nada mas"
    assert normalize_text("vengo ahorita") == "vengo ahora"
    assert normalize_text("PA\u2019L colmado") == "PARA EL tienda"
    assert normalize_text("Voy en guagua") == "Voy en autobus"
    assert normalize_text("'hola' amigo") == "'hola' amigo"
    assert normalize_text("tanto paso") == "tanto paso"
    assert normalize_text("klk") == "hola"
    assert normalize_text("que lo que") == "hola"
    assert normalize_text("dime a ver") == "hola"
    assert normalize_text("manin") == "amigo"
    assert normalize_text("de lo mio") == "amigo"
    assert normalize_text("ta to") == "bien"
    assert normalize_text("quillao") == "enojado"
    assert normalize_text("manso") == "tranquilo"
    assert normalize_text("jevi") == "bueno"
    assert normalize_text("") == ""
    if os.path.exists(DB_PATH):
        bad = verify_lexical()
        assert not bad, "lexical targets missing from DB: %s" % bad
    print("dominican_lexicon: all asserts passed")
