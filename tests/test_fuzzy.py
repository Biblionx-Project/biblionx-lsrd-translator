import unittest

import _common  # noqa: F401
import ml_matcher
import translator


class FuzzyMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fz = translator.LSRDTranslator()._index.fuzzy

    def test_typo_hits_intended_word(self):
        hit = self.fz.match("abogadoo")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["norm"], "abogado")
        self.assertGreaterEqual(hit["score"], 0.84)

    def test_short_words_never_match(self):
        self.assertIsNone(self.fz.match("abg"))
        self.assertIsNone(self.fz.match("ab"))

    def test_unrelated_gibberish_no_match(self):
        self.assertIsNone(self.fz.match("zzzzzz"))
        self.assertIsNone(self.fz.match("xyzqwk"))

    def test_candidates_sorted(self):
        cands = self.fz.candidates("abogadoo", k=5)
        scores = [c["score"] for c in cands]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_damerau_levenshtein(self):
        self.assertEqual(ml_matcher.damerau_levenshtein("casa", "casa"), 0)
        self.assertEqual(ml_matcher.damerau_levenshtein("casa", "csaa"), 1)  # transposition
        self.assertEqual(ml_matcher.damerau_levenshtein("casa", "cas"), 1)

    def test_translator_fuzzy_protected_and_short(self):
        tr = translator.LSRDTranslator()
        self.assertIsNone(tr._fuzzy_sign("senas", ""))
        self.assertIsNone(tr._fuzzy_sign("abg", ""))
        self.assertIsNone(tr._fuzzy_sign("abc123", ""))

    def test_derivational_neighbours_rejected(self):
        tr = translator.LSRDTranslator()
        # Different lexemes, not typos: must not map to the nearest entry.
        for word in ("ingenieria", "arquitectura", "musico"):
            self.assertIsNone(tr._fuzzy_sign(word, ""), word)
        # A real typo still resolves.
        self.assertIsNotNone(tr._fuzzy_sign("abogadoo", ""))


if __name__ == "__main__":
    unittest.main()
