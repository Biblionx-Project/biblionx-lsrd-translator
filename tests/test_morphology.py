import unittest

import _common  # noqa: F401
import morphology
import nlp_engine


class MorphologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = nlp_engine.get_resources().known

    def lem(self, word):
        return morphology.lemmatize(word, self.known)[0]

    def test_regular_verb_tenses(self):
        for form in ("vivieron", "vivimos", "vivire", "vivia"):
            self.assertEqual(self.lem(form), "vivir", form)
        for form in ("estudiaron", "estudiando"):
            self.assertEqual(self.lem(form), "estudiar", form)
        self.assertEqual(self.lem("hablaron"), "hablar")

    def test_irregular_verbs(self):
        cases = {"quiero": "querer", "quisieron": "querer", "tengo": "tener",
                 "dijo": "decir", "hizo": "hacer", "fui": "ir", "fueron": "ser"}
        for form, lemma in cases.items():
            self.assertEqual(self.lem(form), lemma, form)

    def test_plural(self):
        self.assertEqual(self.lem("casas"), "casa")
        self.assertEqual(self.lem("amigos"), "amigo")
        self.assertEqual(self.lem("profesores"), "profesor")

    def test_gender(self):
        self.assertEqual(self.lem("abogada"), "abogado")
        self.assertEqual(self.lem("profesora"), "profesor")

    def test_enclitics(self):
        self.assertEqual(self.lem("estudiarlo"), "estudiar")
        self.assertEqual(self.lem("dime"), "decir")
        self.assertEqual(self.lem("dandole"), "dar")

    def test_known_word_is_exact(self):
        self.assertEqual(morphology.lemmatize("casa", self.known), ("casa", "exact"))

    def test_unknown_word_is_unchanged(self):
        self.assertEqual(morphology.lemmatize("xyzqwk", self.known), ("xyzqwk", "none"))

    def test_protected_senas_not_lemmatized(self):
        eng = nlp_engine.LSRDNlpEngine()
        self.assertEqual(eng._lemmatize("senas"), ("senas", "exact"))
        self.assertEqual(eng._lemmatize("sena"), ("sena", "exact"))

    def test_engine_marks_method(self):
        eng = nlp_engine.LSRDNlpEngine()
        self.assertEqual(eng._lemmatize("casas"), ("casa", "morphology"))
        self.assertEqual(eng._lemmatize("casa"), ("casa", "exact"))


if __name__ == "__main__":
    unittest.main()


class StressedPreteriteTests(unittest.TestCase):
    """The written accent is the only cue separating "trabajó" from "trabajo"."""

    @classmethod
    def setUpClass(cls):
        cls.engine = nlp_engine.LSRDNlpEngine()

    def seq(self, text):
        return list(self.engine.process(text)["secuencia_lsrd"])

    def test_accented_preterite_becomes_verb(self):
        self.assertIn("trabajar", self.seq("Mi hermana no trabajó hoy"))
        self.assertIn("trabajar", self.seq("Ayer trabajé mucho"))

    def test_unaccented_noun_is_kept(self):
        self.assertIn("trabajo", self.seq("Mi trabajo es bueno"))
