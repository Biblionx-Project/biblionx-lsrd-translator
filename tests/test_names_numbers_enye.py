"""Regressions found while testing the extension on real web pages:
proper nouns, numerals, ñ collisions and one-letter function words."""

import unittest

import _common  # noqa: F401
import nlp_engine
import translator


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = nlp_engine.LSRDNlpEngine()
        cls.translator = translator.LSRDTranslator()

    def signs(self, text):
        return self.translator.translate_sequence(self.engine.process(text)["secuencia_lsrd"])

    def lexical(self, text):
        return [s["palabra_es"] for s in self.signs(text) if not s.get("es_deletreo")]

    def spelled(self, text):
        return [s["spelled_word"] for s in self.signs(text)
                if s.get("es_deletreo") and s.get("spelled_index") == 0]


class EnyeTests(_Base):
    def test_ano_is_not_confused_with_year(self):
        self.assertIn("AÑO", self.lexical("Viajó a Santiago el año pasado"))
        self.assertNotIn("ANO", self.lexical("Viajó a Santiago el año pasado"))
        self.assertIn("AÑO", self.lexical("Hace dos años"))

    def test_word_without_enye_never_maps_to_enye_headword(self):
        self.assertNotIn("SOÑAR", self.lexical("El teléfono va a sonar"))
        self.assertIn("SOÑAR", self.lexical("Anoche soñé contigo"))

    def test_una_is_not_dropped_as_article(self):
        self.assertIn("UÑA", self.lexical("Me corté la uña"))

    def test_fingerspelling_keeps_enye(self):
        self.assertIn("niño", self.spelled("Juega con un niño"))


class NameTests(_Base):
    def test_name_is_not_resolved_to_a_common_word(self):
        out = self.lexical("Cruzaron el canal de la Mona ayer")
        self.assertNotIn("MONO, NA", out)
        self.assertIn("mona", self.spelled("Cruzaron el canal de la Mona ayer"))

    def test_multiword_name_without_entry_is_spelled_whole(self):
        self.assertIn("puerto rico", self.spelled("Viajó a Puerto Rico"))
        self.assertNotIn("RICO, CA", self.lexical("Viajó a Puerto Rico"))

    def test_names_in_the_dictionary_keep_their_sign(self):
        self.assertIn("SANTO DOMINGO", self.lexical("Vivo en Santo Domingo"))
        # The province headword is printed with its capital in parentheses (PDF p.434)
        # and is reached through the printed name kept in sinonimos_mapeo.
        self.assertIn("PUERTO PLATA (SAN FELIPE DE PUERTO PLATA)",
                      self.lexical("Mi amiga vive en Puerto Plata"))
        self.assertIn("SANTIAGO (SANTIAGO DE LOS CABALLEROS)",
                      self.lexical("Vivo en Santiago de los Caballeros"))

    def test_capitalized_common_words_keep_their_signs(self):
        out = self.lexical("El Ministerio de Educación abrió la Biblioteca Nacional")
        for sign in ("MINISTERIO", "EDUCACIÓN", "BIBLIOTECA"):
            self.assertIn(sign, out)

    def test_sentence_initial_capital_is_not_a_name(self):
        self.assertIn("MAÑANA", self.lexical("Mañana te llamo"))


class NumberTests(_Base):
    def test_small_numbers_use_number_signs(self):
        out = self.lexical("Tengo 3 hermanos y 10 primos")
        self.assertIn("TRES", out)
        self.assertIn("DIEZ", out)

    def test_long_numbers_are_signed_digit_by_digit(self):
        signs = [s for s in self.signs("En 1844 fue la independencia") if s.get("match_method") == "number"]
        self.assertEqual([s["palabra_es"] for s in signs], ["UNO, UNA", "OCHO", "CUATRO", "CUATRO"])
        self.assertTrue(all(s["number_value"] == "1844" for s in signs))


class OneLetterWordTests(_Base):
    def test_conjunctions_and_prepositions_are_not_letter_signs(self):
        for text in ("Mi hermano y yo", "Vamos a la playa", "Café o té"):
            with self.subTest(text=text):
                letters = [s for s in self.signs(text) if s.get("palabra_es") in ("Y", "A", "O")
                           and not s.get("es_deletreo")]
                self.assertEqual(letters, [])


if __name__ == "__main__":
    unittest.main()
