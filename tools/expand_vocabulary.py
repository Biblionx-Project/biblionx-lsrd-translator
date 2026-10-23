#!/usr/bin/env python3
"""Reviewer helper: find the Spanish words the pipeline fingerspells and propose
related dictionary signs for them.

Why: the official dictionary (lsrd_dictionary.db) has ~2,500 entries, so real
texts get many words fingerspelled letter by letter. Many of those words are
derivationally related to a word that DOES have a sign (llover / lluvia,
recomendar / recomendacion, central / centro, poblada / pueblo). An interpreter
can decide quickly whether the existing sign is also the standard way to express
the related word. This tool produces the shortlist; it never edits the dictionary
and never writes data/synonyms_extra.json.

Vocabulary is harvested from data already on disk:

  * palabras.definicion_es and senas_descripciones.descripcion_sena in the DB
    (thousands of everyday words; accented letters lost to U+FFFD in the source
    are recovered only when exactly one clean word matches the pattern),
  * tests/data/eval_corpus*.json (the "text" of every item),
  * any extra plain-text file given with --text (for example a thesis dump).

Each distinct word is run through the real pipeline (LSRDNlpEngine +
LSRDTranslator, with the AI provider disabled). Words that are dropped as stop
words or that resolve to a sign are discarded; the rest are "fingerspelled".
Words resolved only by a curated-pending-review mapping are kept and marked
status="mapped" so the review file stays stable after mappings are accepted.

Candidates come from shared stems after stripping common derivational suffixes
(-cion, -miento, -dor/-dora, -ado/-ido, -al, -ico, -oso, -ista, -idad,
-ar/-er/-ir ...) plus irregular stem alternations (llov/lluv, pobl/pueb,
pued/pod, ue->o, ie->e ...). Candidates are only hints: a shared stem does not
prove a shared meaning (poder != poderoso), so a human decides.

Output: data/vocabulary_candidates.json  (word, frequency, candidates, ...).

Usage (from the repository root):
    python tools/expand_vocabulary.py
    python tools/expand_vocabulary.py --text path/to/dump.txt --top 5
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Deterministic and free: never reach an AI provider while harvesting.
for _var in ("BIBLIONX_LLM_PROVIDER", "BIBLIONX_LLM_MODEL", "BIBLIONX_LLM_MAX_CALLS"):
    os.environ.pop(_var, None)

from nlp_engine import normalize_word  # noqa: E402

DB_PATH = os.path.join(ROOT, "lsrd_dictionary.db")
EXTRA_PATH = os.path.join(ROOT, "data", "synonyms_extra.json")
OUT_PATH = os.path.join(ROOT, "data", "vocabulary_candidates.json")
CORPUS_GLOB = os.path.join(ROOT, "tests", "data", "eval_corpus*.json")

REPLACEMENT = "�"
_WORD_RE = re.compile("[A-Za-zÀ-ɏ" + REPLACEMENT + "]+")
MIN_WORD_LEN = 3
MIN_STEM_LEN = 4

# --- derivational / inflectional suffixes (accent-stripped, longest match first)
INFLECTION = ("amos", "emos", "imos", "aron", "ieron", "ando", "iendo", "aban", "aba",
              "ada", "ado", "ida", "ido", "adas", "ados", "idas", "idos", "an", "en",
              "ar", "er", "ir", "as", "es", "os", "a", "e", "o", "s", "ia", "io")
DERIVATION = ("amiento", "imiento", "miento", "mento", "acion", "icion", "cion", "sion",
              "adora", "edora", "idora", "ador", "edor", "idor", "dora", "dor", "tora", "tor",
              "ancia", "encia", "ante", "ente", "ismo", "ista", "idad", "dad", "ura",
              "ario", "aria", "ero", "era", "ico", "ica", "oso", "osa", "ivo", "iva",
              "able", "ible", "ense", "eno", "ano", "ana", "ez", "eza", "al", "ud",
              "ia", "io", "ion", "ncia", "nte", "uario", "ero", "ito", "ita")

# --- irregular stem alternations: every variant maps to the group's first member
ALT_GROUPS = (
    ("lluv", "llov"), ("pobl", "pueb", "pob"), ("pod", "pued", "pud"), ("quer", "quier", "quis"),
    ("sent", "sient"), ("cont", "cuent"), ("record", "recuerd"), ("volv", "vuel"),
    ("mor", "muer"), ("dorm", "duerm"), ("encontr", "encuentr"), ("neg", "nieg"),
    ("hac", "hag", "hiz", "hech"), ("dec", "dic", "dij"), ("ten", "tien", "tuv", "teng"),
    ("ven", "vien", "vin", "veng"), ("pon", "pus", "pong"), ("sab", "sep"),
    ("ver", "vis", "vist"), ("escrib", "escrit"), ("abr", "abiert"), ("jug", "jueg"),
    ("cerr", "cierr"), ("empez", "empiez", "empec"), ("pens", "piens"), ("sal", "salg"),
)
_ALT = {}
for _group in ALT_GROUPS:
    for _member in _group:
        _ALT[_member] = _group[0]
_DIPHTHONG = (("ie", "e"), ("ue", "o"), ("ue", "u"), ("hue", "o"))
_SPELLING = (("z", "c"), ("qu", "c"), ("gu", "g"), ("j", "g"), ("c", "z"), ("gu", "g"))


def stem_variants(word):
    """Set of canonical stems of ``word`` (accent-stripped, lowercase)."""
    stems = {word}
    for suffixes in (DERIVATION, INFLECTION, INFLECTION, DERIVATION):
        nxt = set(stems)
        for stem in stems:
            for suf in suffixes:
                if stem.endswith(suf) and len(stem) - len(suf) >= MIN_STEM_LEN - 1:
                    nxt.add(stem[:-len(suf)])
        stems = nxt
    out = set()
    for stem in stems:
        forms = {stem}
        for pat, rep in _DIPHTHONG:
            if pat in stem:
                forms.add(stem.replace(pat, rep, 1))
        for pat, rep in _SPELLING:
            if pat in stem[-3:]:
                forms.add(stem[:len(stem) - 3] + stem[-3:].replace(pat, rep))
        for form in list(forms):
            forms.add(_ALT.get(form, form))
        out |= forms
    return {s for s in out if len(s) >= MIN_STEM_LEN}


# Decisions already taken by the AI curator for words that LOOK mappable but are not.
# They stay fingerspelled (or need a new official sign); the review file shows why.
CURATOR_REJECTIONS = {
    "poder": "meaning shift: the only related sign is PODEROSO (powerful), not the modal verb",
    "publico": "no equivalent sign: PUBLICIDAD (advertising) and PUEBLO are different concepts",
    "publica": "no equivalent sign: PUBLICIDAD (advertising) and PUEBLO are different concepts",
    "ocupa": "no OCUPAR/OCUPADO sign in the dictionary and no standard shared sign",
    "ocupar": "no OCUPAR/OCUPADO sign in the dictionary and no standard shared sign",
    "excepto": "no sign for EXCEPTO/MENOS in the dictionary",
    "haiti": "country name: fingerspell it; HAITIANO (demonym) is a different word",
    "america": "proper noun: fingerspelling names is correct LSRD practice",
    "caribe": "proper noun: fingerspelling names is correct LSRD practice",
    "antillas": "proper noun: fingerspelling names is correct LSRD practice",
    "atlantico": "proper noun: fingerspelling names is correct LSRD practice",
    "puerto": "part of the proper noun Puerto Rico; PUERTA (door) is a different word",
    "femenino": "dictionary FEMENINA/MASCULINA are sexual terms, not the adjectives",
    "masculino": "dictionary FEMENINA/MASCULINA are sexual terms, not the adjectives",
    "permitir": "PERMISO is the polite 'excuse me' sign, not 'allow'",
    "hacer": "no HACER sign in the dictionary: needs an official sign from interpreters",
    "mantener": "no sign for MANTENER; SOSTENER (hold up) and CONTINUAR (go on) are different",
}


# --- vocabulary harvest ------------------------------------------------------
def words_in(text):
    return [m.group(0) for m in _WORD_RE.finditer(text or "")]


def _clean(word):
    norm = normalize_word(word)
    return norm if norm.isalpha() and norm.isascii() else ""


def harvest_db(db_path):
    """Counters of normalized words per DB column; words with U+FFFD kept raw."""
    conn = sqlite3.connect("file:" + db_path.replace("\\", "/") + "?mode=ro", uri=True)
    try:
        defs = [r[0] for r in conn.execute("SELECT definicion_es FROM palabras") if r[0]]
        descs = [r[0] for r in conn.execute("SELECT descripcion_sena FROM senas_descripciones") if r[0]]
        heads = []
        definitions = {}
        for pid, norm, definition in conn.execute(
                "SELECT id, palabra_norm, definicion_es FROM palabras ORDER BY rowid"):
            heads.append((pid, norm or ""))
            definitions[pid] = (definition or "").replace(REPLACEMENT, "?").strip()
    finally:
        conn.close()
    return defs, descs, heads, definitions


def harvest_text(text, counter, capitalised, midsentence):
    """Count words of ``text``; track capitalisation in mid-sentence position."""
    prev_end = True
    for m in _WORD_RE.finditer(text or ""):
        raw = m.group(0)
        start = m.start()
        before = text[max(0, start - 3):start]
        sentence_start = prev_end or bool(re.search(r"[.!?¡¿:]\s*$", before)) or start == 0
        prev_end = False
        if REPLACEMENT in raw:
            counter[normalize_word_keep(raw)] += 1  # repaired later
            continue
        norm = _clean(raw)
        if not norm:
            continue
        counter[norm] += 1
        if not sentence_start:
            midsentence[norm] += 1
            if raw[0].isupper():
                capitalised[norm] += 1


def recover_replacement_words(counter, clean_vocab):
    """Repair 'espa�ol'-style words when exactly one clean word fits."""
    by_len = defaultdict(list)
    for w in clean_vocab:
        by_len[len(w)].append(w)
    fixed = Counter()
    for raw, n in counter.items():
        if REPLACEMENT not in raw:
            fixed[raw] += n
            continue
        pattern = re.compile("^" + re.escape(normalize_word_keep(raw)).replace(
            re.escape(REPLACEMENT), "[a-z]") + "$")
        matches = [w for w in by_len.get(len(raw), []) if pattern.match(w)]
        if len(matches) == 1:
            fixed[matches[0]] += n
    return fixed


def normalize_word_keep(raw):
    """Lowercase + strip accents but keep the U+FFFD placeholder."""
    return "".join(normalize_word(c) or c if c != REPLACEMENT else c for c in raw.lower())


# --- pipeline probe ------------------------------------------------------------
class Probe:
    """Tells which tokens the current pipeline fingerspells."""

    def __init__(self, db_path):
        from nlp_engine import LSRDNlpEngine
        from translator import LSRDTranslator
        self.engine = LSRDNlpEngine(db_path)
        self.translator = LSRDTranslator(db_path)

    def classify(self, word):
        """Return a list of (token, state) with state in 'open' | 'mapped'.

        Stop words and signed words yield nothing. A token resolved only by a
        curated-pending-review mapping is 'mapped'.
        """
        tr = self.translator
        out = []
        for tok in self.engine.process(word)["secuencia_lsrd"]:
            pid, method = tr._lookup_id(tok)
            if pid:
                if method == "curated_synonym" and tok in _PENDING:
                    out.append((tok, "mapped"))
                continue
            if tr._fuzzy_sign(tok, None):
                continue
            out.append((tok, "open"))
        return out


_PENDING = set()
_CURATED = {}


def load_curated(path):
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh).get("entries", [])
    except (OSError, ValueError, AttributeError):
        return
    for e in entries:
        if not isinstance(e, dict) or not e.get("word"):
            continue
        word = normalize_word(e["word"])
        _CURATED[word] = e
        if e.get("source") == "curated-pending-review":
            _PENDING.add(word)


# --- candidate index -----------------------------------------------------------
def build_head_index(heads):
    """{head word: palabra_id} for every single-word dictionary head."""
    index = {}
    for pid, norm in heads:
        norm = norm or ""
        text = re.sub(r"\([^)]*\)", " ", norm.lower())
        text = "".join(c for c in normalize_word_keep(text) if c.isalpha() or c in " ,")
        parts = [p.strip() for p in text.split(",") if p.strip()]
        for i, part in enumerate(parts):
            if " " in part or not part.isalpha():
                continue
            if i == 0 or len(part) >= 4:
                index.setdefault(part, pid)
    return index


def build_stem_index(head_index):
    stem_index = defaultdict(set)
    for head in head_index:
        for stem in stem_variants(head):
            stem_index[stem].add(head)
    return stem_index


def candidates_for(word, head_index, stem_index, top, definitions=None):
    scored = {}
    for stem in stem_variants(word):
        for head in stem_index.get(stem, ()):
            if head == word:
                continue
            ratio = SequenceMatcher(None, word, head).ratio()
            score = round(len(stem) / max(len(word), len(head)) * 0.6 + ratio * 0.4, 3)
            old = scored.get(head)
            if old is None or score > old["score"]:
                scored[head] = {"norm": head, "palabra_id": head_index[head],
                                "stem": stem, "score": score}
                if definitions is not None:
                    scored[head]["definition"] = definitions.get(head_index[head], "")
    ranked = sorted(scored.values(), key=lambda c: (-c["score"], c["norm"]))
    return ranked[:top]


# --- main --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--text", action="append", default=[],
                    help="extra plain-text file to harvest (repeatable)")
    ap.add_argument("--top", type=int, default=5, help="candidates per word")
    ap.add_argument("--min-freq", type=int, default=2,
                    help="keep words seen at least N times, unless they have candidates")
    ap.add_argument("--limit", type=int, default=0, help="cap the words written (0 = all)")
    args = ap.parse_args(argv)

    load_curated(EXTRA_PATH)
    defs, descs, heads, definitions = harvest_db(args.db)

    by_source = {"definitions": Counter(), "sign_descriptions": Counter(),
                 "corpus": Counter(), "text_files": Counter()}
    capitalised, midsentence = Counter(), Counter()
    for text in defs:
        harvest_text(text, by_source["definitions"], capitalised, midsentence)
    for text in descs:
        harvest_text(text, by_source["sign_descriptions"], capitalised, midsentence)
    for path in sorted(glob.glob(CORPUS_GLOB)):
        with open(path, encoding="utf-8") as fh:
            for item in json.load(fh).get("items", []):
                harvest_text(item.get("text", ""), by_source["corpus"], capitalised, midsentence)
    for path in args.text:
        with open(path, encoding="utf-8", errors="replace") as fh:
            harvest_text(fh.read(), by_source["text_files"], capitalised, midsentence)

    clean_vocab = set()
    for counter in by_source.values():
        clean_vocab.update(w for w in counter if REPLACEMENT not in w)
    for name in by_source:
        by_source[name] = recover_replacement_words(by_source[name], clean_vocab)

    total = Counter()
    for counter in by_source.values():
        for w, n in counter.items():
            if len(w) >= MIN_WORD_LEN:
                total[w] += n

    probe = Probe(args.db)
    head_index = build_head_index(heads)
    stem_index = build_stem_index(head_index)

    found = {}          # token -> record
    for word in sorted(total):
        for token, state in probe.classify(word):
            if len(token) < MIN_WORD_LEN or not token.isalpha():
                continue
            rec = found.setdefault(token, {"frequency": 0, "state": state, "forms": Counter(),
                                           "sources": Counter()})
            rec["frequency"] += total[word]
            rec["forms"][word] += total[word]
            for name, counter in by_source.items():
                if counter.get(word):
                    rec["sources"][name] += counter[word]

    words = []
    for token, rec in found.items():
        cands = candidates_for(token, head_index, stem_index, args.top, definitions)
        if rec["frequency"] < args.min_freq and not cands:
            continue
        mids = midsentence.get(token, 0)
        proper = mids >= 2 and capitalised.get(token, 0) / mids >= 0.6
        entry = {"word": token, "frequency": rec["frequency"],
                 "status": "mapped" if rec["state"] == "mapped" else "open",
                 "sources": dict(sorted(rec["sources"].items())),
                 "surface_forms": [w for w, _ in rec["forms"].most_common(5) if w != token],
                 "proper_noun_hint": bool(proper),
                 "candidates": cands}
        cur = _CURATED.get(token)
        if cur:
            entry["curated_target"] = cur.get("target_norm")
        if token in CURATOR_REJECTIONS and entry["status"] == "open":
            entry["status"] = "rejected"
            entry["review_note"] = CURATOR_REJECTIONS[token]
        words.append(entry)
    words.sort(key=lambda e: (-e["frequency"], e["word"]))
    if args.limit:
        words = words[:args.limit]

    report = {
        "version": 1,
        "generated_by": "tools/expand_vocabulary.py",
        "note": ("Review file only. Candidates are derivational hints, not decisions: "
                 "map a word in data/synonyms_extra.json only when the existing sign has "
                 "the same meaning or is the standard LSRD way to express it."),
        "sources": {
            "database": ["palabras.definicion_es", "senas_descripciones.descripcion_sena"],
            "corpora": [os.path.basename(p) for p in sorted(glob.glob(CORPUS_GLOB))],
            "text_files": [os.path.basename(p) for p in args.text],
        },
        "stats": {
            "distinct_words_harvested": len(total),
            "fingerspelled_words": sum(1 for w in words if w["status"] in ("open", "rejected")),
            "rejected_by_curator": sum(1 for w in words if w["status"] == "rejected"),
            "mapped_pending_review": sum(1 for w in words if w["status"] == "mapped"),
            "with_candidates": sum(1 for w in words if w["candidates"]),
        },
        "words": words,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(json.dumps(report["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
