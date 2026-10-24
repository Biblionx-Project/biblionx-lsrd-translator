"""Merge synonym proposals (reach_*.json) into data/synonyms_extra.json.

Each proposal is {"word", "target_id", "target_norm", "confidence", "note"}.
Accepted single-word proposals are appended as "curated-pending-review" entries
that interpreters validate through docs/validation/01_sinonimos_curados.csv.
Multi-word proposals are NOT written to synonyms_extra.json, because the phrase
matcher only reads multi-word sinonimos_mapeo rows; they go to a separate
review file (data/synonyms_phrases_pending.json) for a dictionary owner to
add with an `add_synonym` op.

Safety rules, applied in this order (each rejection has a reason code):
  bad_proposal         missing word/target or word without letters
  unknown_target       target id is not in palabras
  protected_target     fingerspelling letter, or a sexual-term sign
  never_mapped         word is on the meaning-shift / proper-noun deny list
  stopword             the word is dropped before lookup (stop word, auxiliary)
  db_headword          the word is already a headword or a sinonimos_mapeo entry
  already_present      the word is already in synonyms_extra.json (never overridden)
  enye_mismatch        the translator rejects a sign whose printed headword has n-tilde
                       unless the typed word has one too, so the entry could never fire
  inflection_of_other  the word is a regular inflection of a different headword
  meaning_shift        medium confidence and the note signals a different meaning
  conflict             the same word maps to two targets; only a single
                       high-confidence target survives, otherwise all are dropped

Usage:
    python tools/merge_synonym_proposals.py PROPOSAL.json [PROPOSAL.json ...]
    python tools/merge_synonym_proposals.py --dry-run reach_*.json
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import morphology  # noqa: E402
from nlp_engine import (AUXILIARY_VERBS, LSRD_STOP_WORDS, load_synonyms_extra,  # noqa: E402
                        normalize_word, spelling_form)

DB_PATH = os.path.join(ROOT, "lsrd_dictionary.db")
EXTRA_PATH = os.path.join(ROOT, "data", "synonyms_extra.json")
PHRASES_PATH = os.path.join(ROOT, "data", "synonyms_phrases_pending.json")
SOURCE = "curated-pending-review"

# Letters used by fingerspelling must never be a synonym target.
LETTER_IDS = {
    "lsrd_0001", "lsrd_0262", "lsrd_0372", "lsrd_0678", "lsrd_0807", "lsrd_0971",
    "lsrd_1040", "lsrd_1090", "lsrd_1155", "lsrd_1222", "lsrd_1242", "lsrd_1248",
    "lsrd_1327", "lsrd_1475", "lsrd_1526", "lsrd_1527", "lsrd_1582", "lsrd_1799",
    "lsrd_1815", "lsrd_1907", "lsrd_2028", "lsrd_2157", "lsrd_2170", "lsrd_2237",
    "lsrd_2239", "lsrd_2240", "lsrd_2247",
}
# FEMENINA / MASCULINA are sexual terms in the dictionary, never a plain gender word.
SEXUAL_TARGETS = {"lsrd_2321", "lsrd_2323"}
# Meaning shifts and proper nouns that must not be linked to an existing sign
# (same list as tests/test_vocabulary_expansion.py).
NEVER_MAPPED = {"poder", "publico", "publica", "ocupar", "ocupa", "excepto", "america",
                "caribe", "antillas", "atlantico", "haiti", "puerto", "femenino", "masculino",
                "permitir", "generar", "fundar", "asociar", "vision"}

# A medium-confidence note that mentions one of these describes a relation that
# is not plain equivalence: size/degree modifiers, hypernyms, homographs,
# opposites or approximations. Such proposals are dropped.
_SHIFT_NOTE = re.compile(
    r"\b(small|smaller|tiny|big|bigger|large|larger|diminutive|augmentative|superlative|"
    r"very|extreme|intense|stronger|weaker|milder|"
    r"also (?:a |an |the )?(?:verb|noun|adjective|adj|means|word|name|surname|slang)|"
    r"homograph|ambiguous|polysem|different|opposite|antonym|contrary|"
    r"broader|narrower|more general|more specific|generic|specific|hypernym|hyponym|"
    r"type of|kind of|sort of|subtype|category|example of|"
    r"related|loosely|approximate|approx|roughly|not exact|not the same|similar|"
    r"near-synonym|partial|may mean|can mean|could mean|risky|doubtful|unsure|"
    r"vulgar|sexual|offensive|insult)\b", re.I)
# Notes that only describe the current (wrong) behaviour are not a signal.
_DERIVATION_NOTE = re.compile(r"\b(noun of|verb of|adjective of|adverb of|derived|same family|"
                              r"same sign|plural of|feminine of|masculine of|participle)\b", re.I)


def load_proposals(paths):
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("synonyms", []) if isinstance(data, dict) else data
        tag = os.path.basename(path)
        for item in items:
            if isinstance(item, dict):
                out.append(dict(item, _file=tag))
    return out


class Context:
    """Everything a proposal is checked against, built once from the database."""

    def __init__(self, db_path, extra_path):
        con = sqlite3.connect(db_path)
        try:
            self.rows = {pid: (es or "", norm or "")
                         for pid, es, norm in con.execute(
                             "SELECT id, palabra_es, palabra_norm FROM palabras")}
            self.synonym_rows = [s for (s,) in con.execute(
                "SELECT sinonimo_norm FROM sinonimos_mapeo") if s]
        finally:
            con.close()
        self.has_enye = {pid for pid, (es, _n) in self.rows.items() if "ñ" in es.lower()}
        self.headwords = set()
        for _pid, (_es, norm) in self.rows.items():
            self.headwords |= _head_keys(norm)
        self.db_synonyms = set()
        for syn in self.synonym_rows:
            self.db_synonyms |= _head_keys(syn)
        self.existing = {normalize_word(e["word"]) for e in load_synonyms_extra(extra_path)}
        self.known = morphology.build_known(db_path)
        self.by_norm = {}
        for pid, (_es, norm) in self.rows.items():
            for key in _head_keys(norm):
                self.by_norm.setdefault(key, pid)
        self.stop = set(LSRD_STOP_WORDS) | set(AUXILIARY_VERBS)


def _head_keys(norm):
    """Lookup keys a headword answers to: the whole norm, each comma part, and
    the same without a trailing parenthetical qualifier."""
    keys = set()
    norm = normalize_word(norm) if norm else ""
    raw = (norm or "").strip()
    if not raw:
        return keys
    candidates = [raw] + [p.strip() for p in raw.split(",")]
    for cand in candidates:
        cand = " ".join(cand.split())
        if cand:
            keys.add(cand)
    return keys


def _has_enye_word(word):
    return "ñ" in spelling_form(word)


def evaluate(proposals, ctx):
    """Return (accepted_single, accepted_phrases, rejected) where accepted lists hold
    normalized records and rejected is a list of (reason, proposal)."""
    rejected = []
    survivors = []        # (norm_word, record)
    for prop in proposals:
        word_raw = str(prop.get("word") or "").strip()
        pid = prop.get("target_id")
        word = normalize_word(word_raw)
        word = " ".join(word.split())
        if not word or not pid or not re.search(r"[a-z]", word) or any(c.isdigit() for c in word):
            rejected.append(("bad_proposal", prop))
            continue
        if pid not in ctx.rows:
            rejected.append(("unknown_target", prop))
            continue
        if pid in LETTER_IDS or pid in SEXUAL_TARGETS:
            rejected.append(("protected_target", prop))
            continue
        if word in NEVER_MAPPED:
            rejected.append(("never_mapped", prop))
            continue
        if word in ctx.stop:
            rejected.append(("stopword", prop))
            continue
        if word in ctx.headwords or word in ctx.db_synonyms:
            rejected.append(("db_headword", prop))
            continue
        if word in ctx.existing:
            rejected.append(("already_present", prop))
            continue
        if _has_enye_word(word_raw) != (pid in ctx.has_enye):
            rejected.append(("enye_mismatch", prop))
            continue
        confidence = prop.get("confidence") or "medium"
        note = str(prop.get("note") or "")
        if " " not in word:
            lemma, how = morphology.lemmatize(word, ctx.known)
            if lemma != word and how not in ("none", "exact") and lemma in ctx.known:
                target_keys = _head_keys(ctx.rows[pid][1])
                # A guess the reachability test flagged as a false neighbour, or a
                # high-confidence diminutive/feminine collapse ("hijita" -> HIJO),
                # is exactly what a curated entry should override.
                overridable = ("WRONG NEIGHBOUR" in note
                               or (how == "diminutive" and confidence == "high"))
                if lemma not in target_keys and not overridable:
                    rejected.append(("inflection_of_other", prop))
                    continue
        if confidence != "high" and _SHIFT_NOTE.search(_strip_status(note)):
            if not _DERIVATION_NOTE.search(note) or re.search(
                    r"\b(also|homograph|ambiguous|opposite|antonym|different)\b", note, re.I):
                rejected.append(("meaning_shift", prop))
                continue
        survivors.append((word, dict(prop, _word=word, _confidence=confidence)))

    groups = OrderedDict()
    for word, rec in survivors:
        groups.setdefault(word, []).append(rec)
    singles, phrases = [], []
    for word, recs in groups.items():
        targets = OrderedDict()
        for rec in recs:
            targets.setdefault(rec["target_id"], []).append(rec)
        chosen = None
        if len(targets) == 1:
            chosen = next(iter(targets.values()))[0]
            for rec in next(iter(targets.values())):
                if rec["_confidence"] == "high":
                    chosen = rec
                    break
        else:
            high = [t for t, rs in targets.items() if any(r["_confidence"] == "high" for r in rs)]
            if len(high) == 1:
                chosen = next(r for r in targets[high[0]] if r["_confidence"] == "high")
                for t, rs in targets.items():
                    if t != high[0]:
                        rejected.extend(("conflict", r) for r in rs)
            else:
                for rs in targets.values():
                    rejected.extend(("conflict", r) for r in rs)
        if chosen is None:
            continue
        # Duplicates of the chosen proposal (same word and target) are merged.
        for rs in targets.values():
            for rec in rs:
                if rec is not chosen and rec["target_id"] == chosen["target_id"]:
                    rejected.append(("duplicate_proposal", rec))
        (phrases if " " in word else singles).append((word, chosen))
    return singles, phrases, rejected


def _strip_status(note):
    """Remove the 'currently ...' / 'today ...' tail that reports engine behaviour,
    not meaning (it often says 'fuzzy', 'different sign', ...)."""
    return re.split(r"(?:;|\|)?\s*(?:currently|today|now)\b[:\s]", note, maxsplit=1, flags=re.I)[0]


def to_entry(word, rec, ctx):
    pid = rec["target_id"]
    note = _strip_status(str(rec.get("note") or "")).strip(" ;|") or "reviewed proposal"
    note = note[:160]
    entry = OrderedDict()
    entry["word"] = word
    # Same convention as the curated entries: the first alternative of the headword.
    entry["target_norm"] = ctx.rows[pid][1].split(",")[0].strip()
    entry["palabra_id"] = pid
    entry["source"] = SOURCE
    entry["relation"] = "derivation" if _DERIVATION_NOTE.search(note) else "synonym"
    entry["note"] = "%s [%s confidence]" % (note, rec["_confidence"])
    return entry


def dump_entries(path, entries, extra_head=None):
    lines = ['{"version": 1, "entries": [']
    lines.append(",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in entries))
    lines.append("]}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def run(proposal_paths, db_path=DB_PATH, extra_path=EXTRA_PATH, phrases_path=PHRASES_PATH,
        dry_run=False, out=sys.stdout):
    proposals = load_proposals(proposal_paths)
    ctx = Context(db_path, extra_path)
    singles, phrases, rejected = evaluate(proposals, ctx)
    new_entries = [to_entry(w, r, ctx) for w, r in sorted(singles, key=lambda x: (x[1]["target_id"], x[0]))]
    phrase_entries = [to_entry(w, r, ctx) for w, r in sorted(phrases, key=lambda x: (x[1]["target_id"], x[0]))]

    reasons = Counter(reason for reason, _p in rejected)
    print("proposals read:      %d" % len(proposals), file=out)
    print("added (single word): %d" % len(new_entries), file=out)
    print("phrases for review:  %d" % len(phrase_entries), file=out)
    print("rejected:            %d" % len(rejected), file=out)
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  %-20s %d" % (reason, n), file=out)

    if not dry_run:
        with open(extra_path, encoding="utf-8") as fh:
            current = json.load(fh)["entries"]
        dump_entries(extra_path, current + new_entries)
        if phrase_entries:
            with open(phrases_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({
                    "version": 1,
                    "usage": "Multi-word synonyms. synonyms_extra.json cannot hold them (the phrase "
                             "matcher reads sinonimos_mapeo only). A dictionary owner reviews them and "
                             "adds approved ones with an add_synonym op in data/dictionary_fixes.json.",
                    "entries": phrase_entries}, ensure_ascii=False, indent=1) + "\n")
    return {"added": len(new_entries), "phrases": len(phrase_entries),
            "rejected": len(rejected), "reasons": dict(reasons)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("proposals", nargs="+", help="reach_*.json files (globs allowed)")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--extra", default=EXTRA_PATH)
    ap.add_argument("--phrases-out", default=PHRASES_PATH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    paths = []
    for pattern in args.proposals:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])
    run(paths, args.db, args.extra, args.phrases_out, args.dry_run)


if __name__ == "__main__":
    main()
