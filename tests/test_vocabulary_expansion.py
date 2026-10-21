"""Tests for the vocabulary expansion: new stop words, curated mappings and
the tools/expand_vocabulary.py review helper."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

import _common  # noqa: F401
import nlp_engine
from nlp_engine import LSRDNlpEngine, normalize_word
from translator import LSRDTranslator

TOOLS = os.path.join(_common.ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import expand_vocabulary as ev  # noqa: E402

DB_PATH = nlp_engine.DB_PATH
EXTRA_PATH = nlp_engine.SYNONYMS_EXTRA_PATH

# Stop words added by the vocabulary expansion (none has a sign of its own).
ADDED_STOP_WORDS = {
    "lo", "le", "les", "os", "cuales", "quienes", "cuyo", "cuya", "cuyos", "cuyas",
    "ante", "hacia", "segun", "desde", "hasta", "aunque", "pues", "sino",
}
# Words that carry a sign (or content) and must therefore NEVER be dropped.
MUST_STAY = {"mi", "tu", "te", "me", "nos", "no", "y", "o", "pero", "ya", "si", "tambien",
             "mas", "muy", "ni", "entre", "nunca", "nada", "todo", "otro"}
# Meaning shifts and proper nouns that must not be linked to an existing sign.
NEVER_MAPPED = {"poder", "publico", "publica", "ocupar", "ocupa", "excepto", "america",
                "caribe", "antillas", "atlantico", "haiti", "puerto", "femenino", "masculino",
                "permitir", "generar", "fundar", "asociar", "vision"}


def _db_norms():
    conn = sqlite3.connect(DB_PATH)
    try:
        return {normalize_word(n) for (n,) in conn.execute("SELECT palabra_norm FROM palabras") if n}
    finally:
        conn.close()


def _load_extra():
    with open(EXTRA_PATH, encoding="utf-8") as fh:
        return json.load(fh)["entries"]


class StopWordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LSRDNlpEngine()
        cls.translator = LSRDTranslator()

    def test_added_words_are_stop_words(self):
        self.assertTrue(ADDED_STOP_WORDS <= nlp_engine.LSRD_STOP_WORDS)
        self.assertIn("haber", nlp_engine.AUXILIARY_VERBS)

    def test_added_stop_words_have_no_sign_of_their_own(self):
        for word in sorted(ADDED_STOP_WORDS):
            with self.subTest(word=word):
                self.assertEqual(self.translator._lookup_id(word), (None, None))
        self.assertNotIn("haber", self.engine.resources.known)

    def test_words_with_a_sign_are_not_dropped(self):
        for word in sorted(MUST_STAY):
            with self.subTest(word=word):
                self.assertNotIn(word, nlp_engine.LSRD_STOP_WORDS)
                self.assertNotIn(word, nlp_engine.AUXILIARY_VERBS)

    def test_clitics_and_auxiliary_are_dropped_not_spelled(self):
        result = self.engine.process("Lo vi y le dije que hay un libro")
        seq = list(result["secuencia_lsrd"])
        for dropped in ("lo", "le", "haber", "hay"):
            self.assertNotIn(dropped, seq)
        self.assertIn("libro", seq)
        signs = self.translator.translate_sequence(result["secuencia_lsrd"])
        self.assertFalse([s for s in signs if s["es_deletreo"]])

    def test_prepositions_without_sign_are_dropped(self):
        seq = list(self.engine.process("Trabajo desde ayer hasta hoy")["secuencia_lsrd"])
        self.assertNotIn("desde", seq)
        self.assertNotIn("hasta", seq)

    def test_plural_wh_words_survive_in_questions(self):
        result = self.engine.process("¿Cuáles son los libros?")
        self.assertIn("cuales", result["tokens_filtrados"])
        statement = self.engine.process("Los libros cuales son")
        self.assertNotIn("cuales", statement["tokens_filtrados"])

    def test_negation_is_never_dropped(self):
        seq = list(self.engine.process("Ni Juan vino y no come")["secuencia_lsrd"])
        self.assertIn("ni", seq)
        self.assertIn("no", seq)


class CuratedMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LSRDNlpEngine()
        cls.translator = LSRDTranslator()
        cls.entries = _load_extra()
        cls.pending = [e for e in cls.entries if e.get("source") == "curated-pending-review"]

    def sign_names(self, text):
        result = self.engine.process(text)
        return [(s["palabra_es"], s["match_method"], s["es_deletreo"])
                for s in self.translator.translate_sequence(result["secuencia_lsrd"])]

    def assert_maps_to(self, text, palabra_id):
        result = self.engine.process(text)
        signs = self.translator.translate_sequence(result["secuencia_lsrd"])
        self.assertIn(palabra_id, [s["id"] for s in signs], text)
        self.assertFalse([s for s in signs if s["es_deletreo"]], "still fingerspelled: " + text)

    def test_sample_mappings_reach_the_expected_sign(self):
        samples = {
            "llover": "lluvia", "Ayer llovió mucho": "lluvia", "recomienda": "recomendacion",
            "La región central": "centro", "una isla poblada": "pueblo",
            "está ubicado": "lugar", "la parte oriental": "este",
            "los habitantes": "gente", "utilizar": "usar", "comprender": "entender",
            "colocar": "poner", "la economía": "economia", "gratuita": "gratis",
        }
        conn = sqlite3.connect(DB_PATH)
        try:
            for text, norm in samples.items():
                pids = {r[0] for r in conn.execute(
                    "SELECT id FROM palabras WHERE palabra_norm = ? OR palabra_norm LIKE ?",
                    (norm, norm + " (%"))}
                with self.subTest(text=text):
                    result = self.engine.process(text)
                    signs = self.translator.translate_sequence(result["secuencia_lsrd"])
                    self.assertTrue(pids & {s["id"] for s in signs}, (text, norm))
        finally:
            conn.close()

    def test_mapped_words_are_signed_with_curated_method(self):
        for word in ("llover", "recomendar", "ubicado", "oriental"):
            with self.subTest(word=word):
                pid, method = self.translator._lookup_id(word)
                self.assertIsNotNone(pid)
                self.assertEqual(method, "curated_synonym")

    def test_new_entries_are_marked_for_review_and_point_to_real_signs(self):
        self.assertGreaterEqual(len(self.pending), 500)
        conn = sqlite3.connect(DB_PATH)
        try:
            ids = {r[0] for r in conn.execute("SELECT id FROM palabras")}
        finally:
            conn.close()
        for entry in self.pending:
            self.assertIn(entry["palabra_id"], ids, entry)
            self.assertTrue(entry.get("target_norm"), entry)
            self.assertTrue(entry.get("note"), entry)

    def test_every_entry_has_a_unique_normalized_word(self):
        words = [normalize_word(e["word"]) for e in self.entries]
        self.assertEqual(len(words), len(set(words)))
        for entry in self.entries:
            self.assertEqual(entry["word"], normalize_word(entry["word"]), entry)

    def test_no_entry_shadows_a_dictionary_word(self):
        norms = _db_norms()
        shadowed = [e["word"] for e in self.pending if e["word"] in norms]
        self.assertEqual(shadowed, [])

    def test_rejected_meaning_shifts_and_proper_nouns_stay_unmapped(self):
        mapped = {e["word"] for e in self.entries}
        self.assertEqual(sorted(mapped & NEVER_MAPPED), [])

    def test_country_names_are_not_mapped_to_demonyms(self):
        self.assertEqual(self.translator._lookup_id("haiti"), (None, None))
        self.assertEqual(self.translator._lookup_id("america"), (None, None))

    def test_sexual_terms_are_never_a_target(self):
        # FEMENINA / MASCULINA / MASTURBACION in the dictionary are sexual terms.
        banned = {"lsrd_2321", "lsrd_2323"}
        self.assertFalse([e["word"] for e in self.pending if e["palabra_id"] in banned])


class ExpandVocabularyToolTests(unittest.TestCase):
    def test_related_words_share_a_stem(self):
        pairs = [("llover", "lluvia"), ("recomendar", "recomendacion"), ("central", "centro"),
                 ("poblada", "pueblo"), ("poblacion", "pueblo"), ("expresion", "expresar")]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertTrue(ev.stem_variants(a) & ev.stem_variants(b))

    def test_unrelated_words_do_not_share_a_stem(self):
        self.assertFalse(ev.stem_variants("llover") & ev.stem_variants("mesa"))
        self.assertFalse(ev.stem_variants("excepto") & ev.stem_variants("lluvia"))

    def test_candidates_only_propose_existing_heads(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            heads = [(pid, norm or "") for pid, norm in conn.execute(
                "SELECT id, palabra_norm FROM palabras")]
        finally:
            conn.close()
        head_index = ev.build_head_index(heads)
        stem_index = ev.build_stem_index(head_index)
        cands = ev.candidates_for("llover", head_index, stem_index, 5)
        self.assertIn("lluvia", [c["norm"] for c in cands])
        for cand in cands:
            self.assertEqual(head_index[cand["norm"]], cand["palabra_id"])

    def test_words_with_replacement_char_are_recovered_only_when_unique(self):
        counter = ev.Counter({"espa�ol": 2})
        fixed = ev.recover_replacement_words(counter, {"espanol", "espaxol"})
        self.assertEqual(fixed.get("espanol", 0) + fixed.get("espaxol", 0), 0)  # ambiguous
        fixed = ev.recover_replacement_words(ev.Counter({"espa�ol": 2}), {"espanol"})
        self.assertEqual(fixed["espanol"], 2)

    def test_tool_writes_a_review_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "candidates.json")
            sample = os.path.join(tmp, "sample.txt")
            with open(sample, "w", encoding="utf-8") as fh:
                fh.write("Va a llover. Llover es raro. Excepto el poder en Puerto Rico y Haiti.")
            self.assertEqual(ev.main(["--out", out, "--text", sample, "--min-freq", "1"]), 0)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
        words = {w["word"]: w for w in report["words"]}
        self.assertIn("excepto", words)
        self.assertEqual(words["excepto"]["status"], "rejected")
        self.assertEqual(words["excepto"]["candidates"], [])
        for key in ("word", "frequency", "candidates", "status", "sources"):
            self.assertIn(key, words["excepto"])
        # llover is already mapped (curated-pending-review): kept for traceability
        self.assertEqual(words["llover"]["status"], "mapped")
        self.assertEqual(words["llover"]["curated_target"], "lluvia")
        self.assertGreater(report["stats"]["distinct_words_harvested"], 1000)


if __name__ == "__main__":
    unittest.main()
