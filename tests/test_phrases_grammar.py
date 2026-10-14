import unittest

import _common  # noqa: F401
import grammar
import nlp_engine
from phrases import PhraseMatcher


class PhraseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pm = nlp_engine.get_resources().phrases

    def test_longest_match_merges(self):
        self.assertEqual(self.pm.segment(["buenos", "dias", "amigo"]), ["buenos dias", "amigo"])
        self.assertEqual(self.pm.segment(["a", "traves", "de", "casa"])[0], "a traves")

    def test_non_phrase_unchanged(self):
        self.assertEqual(self.pm.segment(["casa", "grande"]), ["casa", "grande"])
        self.assertEqual(self.pm.segment([]), [])

    def test_greedy_prefers_longer(self):
        pm = PhraseMatcher({"a b": "AB", "a b c": "ABC"})
        self.assertEqual(pm.segment(["a", "b", "c", "d"]), ["ABC", "d"])
        self.assertEqual(pm.segment(["a", "b", "d"]), ["AB", "d"])

    def test_phrase_through_engine(self):
        res = nlp_engine.LSRDNlpEngine().process("buenos d\u00edas")
        self.assertEqual(list(res["secuencia_lsrd"]), ["buenos dias"])
        self.assertEqual(res["secuencia_lsrd"].methods, ["phrase"])


class GrammarTests(unittest.TestCase):
    def test_time_first(self):
        self.assertEqual(grammar.reorder(["casa", "ayer", "ir"]), ["ayer", "casa", "ir"])

    def test_negation_last(self):
        self.assertEqual(grammar.reorder(["no", "comer", "pan"]), ["comer", "pan", "no"])

    def test_time_and_negation(self):
        self.assertEqual(grammar.reorder(["casa", "ayer", "no", "comer"]),
                         ["ayer", "casa", "comer", "no"])

    def test_question_word_moves_to_end_only_in_questions(self):
        self.assertEqual(grammar.reorder(["donde", "vivir", "tu"], True), ["vivir", "tu", "donde"])
        self.assertEqual(grammar.reorder(["donde", "vivir"], False), ["donde", "vivir"])
        self.assertEqual(grammar.reorder(["¿por que?", "llorar"], True), ["llorar", "¿por que?"])
        self.assertEqual(grammar.reorder(["por que", "llorar"], True), ["llorar", "por que"])
        self.assertEqual(grammar.reorder(["para que", "llorar"], True), ["llorar", "para que"])

    def test_empty(self):
        self.assertEqual(grammar.reorder([]), [])

    def test_question_detection(self):
        self.assertTrue(grammar.is_question_text("\u00bfD\u00f3nde vives?"))
        self.assertFalse(grammar.is_question_text("Vivo aqui."))

    def test_clause_split_flags_questions(self):
        clauses = grammar.split_clauses_flagged("Hola, \u00bfc\u00f3mo est\u00e1s? Bien.")
        self.assertEqual([flag for _, flag in clauses], [False, True, False])

    def test_engine_end_to_end_order(self):
        eng = nlp_engine.LSRDNlpEngine()
        self.assertEqual(list(eng.process("Hoy no llueve")["secuencia_lsrd"])[-1], "no")
        self.assertEqual(list(eng.process("Ayer yo com\u00ed pan")["secuencia_lsrd"])[0], "ayer")
        res = eng.process("\u00bfD\u00f3nde vive el abogado?")
        self.assertTrue(res["is_question"])
        self.assertEqual(list(res["secuencia_lsrd"]), ["vivir", "abogado", "donde"])
        res_por_que = eng.process("\u00bfPor qu\u00e9 lloras?")
        self.assertTrue(res_por_que["is_question"])
        self.assertEqual(list(res_por_que["secuencia_lsrd"]), ["llorar", "\u00bfpor que?"])

    def test_process_keys(self):
        res = nlp_engine.LSRDNlpEngine().process("casa")
        for key in ("original_text", "tokens_normalizados", "tokens_filtrados",
                    "tokens_lematizados", "secuencia_lsrd", "normalized_text",
                    "is_question", "lemmatization_methods"):
            self.assertIn(key, res)
        self.assertIsInstance(res["secuencia_lsrd"], list)


if __name__ == "__main__":
    unittest.main()
