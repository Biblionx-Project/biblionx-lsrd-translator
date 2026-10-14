import unittest

import _common  # noqa: F401
import nlp_engine
import translator


class _ExplodingLLM:
    """Stands in for a provider; any call is a test failure."""
    enabled = True

    def choose(self, *a, **k):
        raise AssertionError("LLM must not be called")


class TranslatorChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr = translator.LSRDTranslator()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def methods(self, tokens):
        return [s["match_method"] for s in self.tr.translate_sequence(tokens)]

    def test_exact(self):
        out = self.tr.translate_sequence(["abogado"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["match_method"], "exact")
        self.assertEqual(out[0]["confidence"], 1.0)
        self.assertFalse(out[0]["es_deletreo"])
        self.assertTrue(out[0]["id"].startswith("lsrd_"))

    def test_question_words_match_official_signs(self):
        for q_word, expected_id in [("donde", "lsrd_2374"), ("que", "lsrd_2377"),
                                    ("como", "lsrd_2370"), ("cual", "lsrd_2371"),
                                    ("cuando", "lsrd_2372"), ("quien", "lsrd_2378"),
                                    ("por que", "lsrd_2375")]:
            out = self.tr.translate_sequence([q_word])
            self.assertEqual(len(out), 1, f"Failed for {q_word}")
            self.assertEqual(out[0]["match_method"], "exact", f"Failed for {q_word}")
            self.assertEqual(out[0]["id"], expected_id, f"Failed for {q_word}")
            self.assertFalse(out[0]["es_deletreo"], f"Failed for {q_word}")

    def test_fuzzy(self):
        out = self.tr.translate_sequence(["abogadoo"])
        self.assertEqual(out[0]["match_method"], "fuzzy")
        self.assertLess(out[0]["confidence"], 1.0)
        self.assertEqual(out[0]["matched_norm"], "abogado")

    def test_fingerspelling(self):
        out = self.tr.translate_sequence(["xyzqwk"])
        self.assertTrue(out)
        self.assertTrue(all(s["match_method"] == "fingerspelling" and s["es_deletreo"] for s in out))
        self.assertEqual("".join(s["letra"] for s in out), "XYZQWK")

    def test_number_word(self):
        self.assertIn(self.methods(["cinco"])[0], ("exact", "synonym", "curated_synonym"))

    def test_protected_senas_is_not_fuzzy(self):
        self.assertNotIn("fuzzy", self.methods(["senas"]))

    def test_provenance_labels_from_pipeline(self):
        eng = nlp_engine.LSRDNlpEngine()
        seq = eng.process("buenos d\u00edas")["secuencia_lsrd"]
        self.assertEqual(self.methods(seq), ["phrase"])
        seq = eng.process("casas")["secuencia_lsrd"]
        self.assertEqual(self.methods(seq), ["morphology"])

    def test_returned_rows_are_independent_copies(self):
        a = self.tr.translate_sequence(["casa"])[0]
        a["match_method"] = "tampered"
        b = self.tr.translate_sequence(["casa"])[0]
        self.assertEqual(b["match_method"], "exact")

    def test_empty_sequence(self):
        self.assertEqual(self.tr.translate_sequence([]), [])

    def test_exact_and_fuzzy_never_call_llm(self):
        tr = translator.LSRDTranslator(llm=_ExplodingLLM())
        try:
            self.assertEqual(tr.translate_sequence(["casa"])[0]["match_method"], "exact")
            self.assertEqual(tr.translate_sequence(["abogadoo"])[0]["match_method"], "fuzzy")
        finally:
            tr.close()


if __name__ == "__main__":
    unittest.main()
