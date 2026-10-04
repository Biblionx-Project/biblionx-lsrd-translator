import unittest

import _common  # noqa: F401
import dominican_lexicon as dl
import nlp_engine


class DominicanNormalizationTests(unittest.TestCase):
    def test_apocope_variants(self):
        self.assertEqual(dl.normalize_text("vamo a ir"), "vamos a ir")
        self.assertEqual(dl.normalize_text("toy en casa"), "estoy en casa")

    def test_pa_becomes_para(self):
        self.assertEqual(dl.normalize_text("pa ti"), "para ti")
        self.assertEqual(dl.normalize_text("pa' ti"), "para ti")

    def test_case_is_preserved(self):
        self.assertEqual(dl.normalize_text("Pa"), "Para")

    def test_standard_text_untouched(self):
        text = "El abogado vive en la casa."
        self.assertEqual(dl.normalize_text(text), text)

    def test_empty_input(self):
        self.assertEqual(dl.normalize_text(""), "")
        self.assertIsNone(dl.normalize_text(None))

    def test_lexical_targets_exist_in_dictionary(self):
        self.assertEqual(dl.verify_lexical(), [])

    def test_normalize_word_strips_accents_and_punctuation(self):
        self.assertEqual(nlp_engine.normalize_word("\u00c1rbol,"), "arbol")
        self.assertEqual(nlp_engine.normalize_word("  Ni\u00f1o! "), "nino")


if __name__ == "__main__":
    unittest.main()
