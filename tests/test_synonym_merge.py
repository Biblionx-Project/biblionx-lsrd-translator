"""Tests for tools/merge_synonym_proposals.py: conflict and safety rules, plus
invariants of the merged data/synonyms_extra.json."""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

import _common  # noqa: F401
import nlp_engine
from nlp_engine import normalize_word

TOOLS = os.path.join(_common.ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import merge_synonym_proposals as msp  # noqa: E402

DB_PATH = nlp_engine.DB_PATH
EXTRA_PATH = nlp_engine.SYNONYMS_EXTRA_PATH

# (id, palabra_es, palabra_norm)
ROWS = [
    ("lsrd_0001", "A", "a"),                      # fingerspelling letter
    ("lsrd_0100", "CARRO", "carro"),
    ("lsrd_0101", "BOLSA", "bolsa"),
    ("lsrd_0102", "FILA", "fila"),
    ("lsrd_0103", "NIÑO", "nino"),
    ("lsrd_0104", "BAÑERA", "banera"),
    ("lsrd_0105", "HIJO", "hijo"),
    ("lsrd_0106", "HIJA", "hija"),
    ("lsrd_0107", "SACERDOTE", "sacerdote"),
    ("lsrd_0108", "CASA", "casa"),
    ("lsrd_2321", "FEMENINA", "femenina"),
]


def make_env(existing=()):
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE palabras (id TEXT PRIMARY KEY, palabra_es TEXT, palabra_norm TEXT)")
    con.execute("CREATE TABLE sinonimos_mapeo (id INTEGER PRIMARY KEY, palabra_id TEXT, sinonimo_norm TEXT)")
    con.executemany("INSERT INTO palabras VALUES (?,?,?)", ROWS)
    con.execute("INSERT INTO sinonimos_mapeo (palabra_id, sinonimo_norm) VALUES ('lsrd_0108', 'hogar')")
    con.commit()
    con.close()
    extra = os.path.join(tmp, "extra.json")
    with open(extra, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "entries": list(existing)}, fh)
    return tmp, db, extra


def prop(word, pid, norm, conf="high", note="synonym"):
    return {"word": word, "target_id": pid, "target_norm": norm, "confidence": conf, "note": note}


class MergeRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.extra = make_env(
            [{"word": "auto", "target_norm": "carro", "palabra_id": "lsrd_0100", "source": "curated"}])
        self.ctx = msp.Context(self.db, self.extra)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def evaluate(self, *props):
        singles, phrases, rejected = msp.evaluate(list(props), self.ctx)
        return ({w: r["target_id"] for w, r in singles}, {w: r["target_id"] for w, r in phrases},
                [(reason, p["word"]) for reason, p in rejected])

    def test_plain_synonym_is_accepted_and_normalized(self):
        singles, _p, rej = self.evaluate(prop("Cartera", "lsrd_0101", "bolsa"),
                                         prop("hilérA", "lsrd_0102", "fila"))
        self.assertEqual(singles, {"cartera": "lsrd_0101", "hilera": "lsrd_0102"})
        self.assertEqual(rej, [])

    def test_existing_entry_is_never_overridden(self):
        singles, _p, rej = self.evaluate(prop("auto", "lsrd_0101", "bolsa"))
        self.assertEqual(singles, {})
        self.assertEqual(rej, [("already_present", "auto")])

    def test_db_headwords_and_db_synonyms_are_never_overridden(self):
        singles, _p, rej = self.evaluate(prop("carro", "lsrd_0101", "bolsa"),
                                         prop("hogar", "lsrd_0101", "bolsa"))
        self.assertEqual(singles, {})
        self.assertEqual({r for r, _w in rej}, {"db_headword"})

    def test_stopwords_and_auxiliaries_are_rejected(self):
        singles, _p, rej = self.evaluate(prop("el", "lsrd_0101", "bolsa"), prop("fue", "lsrd_0101", "bolsa"))
        self.assertEqual(singles, {})
        self.assertEqual({r for r, _w in rej}, {"stopword"})

    def test_bad_targets_are_rejected(self):
        singles, _p, rej = self.evaluate(
            prop("xyzzy", "lsrd_9999", "nada"),          # unknown id
            prop("alfa", "lsrd_0001", "a"),              # fingerspelling letter
            prop("mujeril", "lsrd_2321", "femenina"),    # sexual term
            prop("poder", "lsrd_0101", "bolsa"))         # deny list
        self.assertEqual(singles, {})
        self.assertEqual(sorted(r for r, _w in rej),
                         ["never_mapped", "protected_target", "protected_target", "unknown_target"])

    def test_review_rejected_homographs_are_dropped(self):
        singles, _p, rej = self.evaluate(prop("super", "lsrd_0101", "bolsa"),
                                         prop("evacuar", "lsrd_0101", "bolsa"))
        self.assertEqual(singles, {})
        self.assertEqual({r for r, _w in rej}, {"review_rejected"})

    def test_enye_target_needs_enye_in_the_typed_word(self):
        singles, _p, rej = self.evaluate(
            prop("chico", "lsrd_0103", "nino"),                 # typed without n-tilde: translator rejects
            prop("tina", "lsrd_0104", "banera"),
            prop("pequeño", "lsrd_0103", "nino"),               # typed with n-tilde: reachable
            prop("cuarto", "lsrd_0102", "fila"))
        self.assertEqual(singles, {"pequeno": "lsrd_0103", "cuarto": "lsrd_0102"})
        self.assertEqual(sorted(w for r, w in rej if r == "enye_mismatch"), ["chico", "tina"])

    def test_conflict_keeps_the_single_high_confidence_target(self):
        singles, _p, rej = self.evaluate(
            prop("pelotilla", "lsrd_0101", "bolsa", "medium"),
            prop("pelotilla", "lsrd_0102", "fila", "high"))
        self.assertEqual(singles, {"pelotilla": "lsrd_0102"})
        self.assertEqual(rej, [("conflict", "pelotilla")])

    def test_conflict_between_two_high_targets_drops_both(self):
        singles, _p, rej = self.evaluate(
            prop("pelotilla", "lsrd_0101", "bolsa", "high"),
            prop("pelotilla", "lsrd_0102", "fila", "high"))
        self.assertEqual(singles, {})
        self.assertEqual([r for r, _w in rej], ["conflict", "conflict"])

    def test_conflict_between_two_medium_targets_drops_both(self):
        singles, _p, rej = self.evaluate(
            prop("pelotilla", "lsrd_0101", "bolsa", "medium"),
            prop("pelotilla", "lsrd_0102", "fila", "medium"))
        self.assertEqual(singles, {})
        self.assertEqual(len(rej), 2)

    def test_conflict_is_found_across_accent_variants(self):
        singles, _p, rej = self.evaluate(
            prop("clérigo", "lsrd_0107", "sacerdote", "medium"),
            prop("clerigo", "lsrd_0108", "casa", "medium"))
        self.assertEqual(singles, {})
        self.assertEqual(len(rej), 2)

    def test_same_target_duplicates_are_merged(self):
        singles, _p, rej = self.evaluate(
            prop("cartera", "lsrd_0101", "bolsa", "medium"),
            prop("cartera", "lsrd_0101", "bolsa", "high"))
        self.assertEqual(singles, {"cartera": "lsrd_0101"})
        self.assertEqual(rej, [("duplicate_proposal", "cartera")])

    def test_medium_meaning_shifts_are_dropped_but_high_ones_are_not(self):
        singles, _p, rej = self.evaluate(
            prop("casita", "lsrd_0108", "casa", "medium", "small house; today -> SPELL:CASITA"),
            prop("bolsita", "lsrd_0101", "bolsa", "medium", "also verb of bolsear"),
            prop("morral", "lsrd_0101", "bolsa", "medium", "bag; currently fuzzy to a different sign"),
            prop("zurron", "lsrd_0101", "bolsa", "high", "small bag"))
        self.assertEqual(singles, {"morral": "lsrd_0101", "zurron": "lsrd_0101"})
        self.assertEqual(sorted(w for r, w in rej if r == "meaning_shift"), ["bolsita", "casita"])

    def test_regular_inflections_of_another_headword_are_rejected(self):
        # "carros" is the plural of CARRO: it must not be redirected to another sign.
        singles, _p, rej = self.evaluate(prop("carros", "lsrd_0101", "bolsa"))
        self.assertEqual(singles, {})
        self.assertEqual(rej, [("inflection_of_other", "carros")])

    def test_false_neighbour_guesses_may_be_overridden(self):
        singles, _p, rej = self.evaluate(
            prop("hijita", "lsrd_0106", "hija", "high", "currently diminutive collapses to HIJO"))
        self.assertEqual(singles, {"hijita": "lsrd_0106"})
        self.assertEqual(rej, [])

    def test_multiword_proposals_go_to_the_phrase_list(self):
        singles, phrases, _rej = self.evaluate(prop("Hacer Fila", "lsrd_0102", "fila"))
        self.assertEqual(singles, {})
        self.assertEqual(phrases, {"hacer fila": "lsrd_0102"})


class MergeRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db, self.extra = make_env(
            [{"word": "auto", "target_norm": "carro", "palabra_id": "lsrd_0100", "source": "curated"}])
        self.proposals = os.path.join(self.tmp, "reach_X.json")
        with open(self.proposals, "w", encoding="utf-8") as fh:
            json.dump({"synonyms": [
                prop("cartera", "lsrd_0101", "bolsa"),
                prop("hacer fila", "lsrd_0102", "fila"),
                prop("auto", "lsrd_0101", "bolsa"),
            ]}, fh)
        self.phrases = os.path.join(self.tmp, "phrases.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_appends_without_touching_existing_entries_and_is_idempotent(self):
        stats = msp.run([self.proposals], self.db, self.extra, self.phrases, out=io.StringIO())
        self.assertEqual((stats["added"], stats["phrases"], stats["rejected"]), (1, 1, 1))
        with open(self.extra, encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        self.assertEqual([e["word"] for e in entries], ["auto", "cartera"])
        self.assertEqual(entries[0]["source"], "curated")
        self.assertEqual(entries[1]["source"], "curated-pending-review")
        self.assertEqual(entries[1]["palabra_id"], "lsrd_0101")
        self.assertEqual(entries[1]["target_norm"], "bolsa")
        self.assertTrue(entries[1]["note"])
        again = msp.run([self.proposals], self.db, self.extra, self.phrases, out=io.StringIO())
        self.assertEqual(again["added"], 0)
        with open(self.extra, encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["entries"]), 2)

    def test_dry_run_writes_nothing(self):
        with open(self.extra, encoding="utf-8") as fh:
            before = fh.read()
        msp.run([self.proposals], self.db, self.extra, self.phrases, dry_run=True, out=io.StringIO())
        with open(self.extra, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(self.phrases))


class MergedDataTests(unittest.TestCase):
    """Invariants of the real, merged data/synonyms_extra.json."""

    @classmethod
    def setUpClass(cls):
        with open(EXTRA_PATH, encoding="utf-8") as fh:
            cls.entries = json.load(fh)["entries"]
        con = sqlite3.connect(DB_PATH)
        try:
            cls.rows = {pid: (es or "", norm or "") for pid, es, norm in
                        con.execute("SELECT id, palabra_es, palabra_norm FROM palabras")}
        finally:
            con.close()

    def test_every_target_exists_and_is_a_real_sign(self):
        for e in self.entries:
            with self.subTest(word=e["word"]):
                self.assertIn(e["palabra_id"], self.rows)
                self.assertNotIn(e["palabra_id"], msp.LETTER_IDS)
                self.assertNotIn(e["palabra_id"], msp.SEXUAL_TARGETS)

    def test_words_are_unique_normalized_single_words(self):
        seen = set()
        for e in self.entries:
            with self.subTest(word=e["word"]):
                self.assertEqual(e["word"], normalize_word(e["word"]))
                self.assertNotIn(" ", e["word"])
                self.assertNotIn(e["word"], seen)
                seen.add(e["word"])

    def test_pending_entries_never_shadow_headwords_or_stopwords(self):
        heads = set()
        for _es, norm in self.rows.values():
            heads |= msp._head_keys(norm)
        stop = nlp_engine.LSRD_STOP_WORDS | nlp_engine.AUXILIARY_VERBS
        for e in self.entries:
            if e["source"] == msp.SOURCE:
                with self.subTest(word=e["word"]):
                    self.assertNotIn(e["word"], heads)
                    self.assertNotIn(e["word"], stop)
                    self.assertNotIn(e["word"], msp.NEVER_MAPPED)
                    self.assertNotIn(e["word"], msp.REVIEW_REJECTED)

    def test_pending_entries_are_documented(self):
        pending = [e for e in self.entries if e["source"] == msp.SOURCE]
        self.assertGreaterEqual(len(pending), 1500)
        for e in pending:
            with self.subTest(word=e["word"]):
                self.assertTrue(e.get("note"))
                self.assertTrue(e.get("target_norm"))

    def test_merged_synonyms_reach_their_sign(self):
        from translator import LSRDTranslator
        tr = LSRDTranslator()
        try:
            checked = 0
            for word in ("espejuelos", "tajalapiz", "reiterar"):
                entry = next((e for e in self.entries if e["word"] == word), None)
                if entry is None:
                    continue
                checked += 1
                with self.subTest(word=word):
                    pid, _method = tr._lookup_id(word)
                    self.assertEqual(pid, entry["palabra_id"])
            self.assertGreaterEqual(checked, 1)
        finally:
            tr.close()


if __name__ == "__main__":
    unittest.main()
