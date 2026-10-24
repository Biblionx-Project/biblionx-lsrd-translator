"""Gender suffixes of headwords ('abogado, da', 'nosotros, tras') are not words."""

import unittest

import _common  # noqa: F401
import ml_matcher
import nlp_engine
import translator


class GenderSuffixTests(unittest.TestCase):
    def test_suffix_is_not_a_key(self):
        keys = ml_matcher._split_variants("nosotros, tras")
        self.assertNotIn("tras", keys)
        self.assertIn("nosotras", keys)
        self.assertNotIn("da", ml_matcher._split_variants("abogado, da"))
        self.assertIn("debajo", ml_matcher._split_variants("abajo, debajo"))

    def test_tras_does_not_become_nosotros(self):
        engine, tr = nlp_engine.LSRDNlpEngine(), translator.LSRDTranslator()
        seq = tr.translate_sequence(engine.process("Tras la guerra llegó la paz")["secuencia_lsrd"])
        self.assertNotIn("NOSOTROS, TRAS", [s["palabra_es"] for s in seq])


if __name__ == "__main__":
    unittest.main()
