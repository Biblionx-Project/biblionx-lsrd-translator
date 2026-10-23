"""Tests for scripts/evaluate.py (metrics) and scripts/check_metrics.py (quality gate)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

import _common

sys.path.insert(0, os.path.join(_common.ROOT, "scripts"))
import check_metrics  # noqa: E402
import evaluate as ev  # noqa: E402

CORPUS_PATH = os.path.join(_common.ROOT, "tests", "data", "eval_corpus.json")
REALISTIC_PATH = os.path.join(_common.ROOT, "tests", "data", "eval_corpus_realistic.json")


def run_gate(metrics, *flags):
    """Run check_metrics.main on a metrics dict; returns (exit code, output)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metrics, f)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_metrics.main([path, *flags])
    return code, out.getvalue() + err.getvalue()


class HelperTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(ev.percentile([], 95), 0.0)
        self.assertEqual(ev.percentile([7], 50), 7.0)
        self.assertEqual(ev.percentile([1, 2, 3, 4, 5], 50), 3.0)
        self.assertAlmostEqual(ev.percentile([0, 10], 95), 9.5)
        self.assertEqual(ev.percentile([5, 1, 3], 100), 5.0)

    def test_order_score(self):
        self.assertEqual(ev.order_score(["ayer", "comer", "no"], ["ayer", "comer", "no"]), (True, 3, 3))
        ok, pairs_ok, total = ev.order_score(["comer", "ayer", "no"], ["ayer", "comer", "no"])
        self.assertFalse(ok)
        self.assertEqual((pairs_ok, total), (2, 3))
        # A missing lemma fails the entry and every pair involving it.
        ok, pairs_ok, total = ev.order_score(["ayer", "no"], ["ayer", "comer", "no"])
        self.assertFalse(ok)
        self.assertEqual((pairs_ok, total), (1, 3))

    def test_token_record(self):
        word = {"es_deletreo": False, "match_method": "morphology", "confidence": 0.9}
        rec = ev.token_record("trabajar", [word])
        self.assertEqual((rec["spelled"], rec["method"], rec["confidence"]), (False, "morphology", 0.9))
        letters = [{"es_deletreo": True, "match_method": "fingerspelling", "confidence": 0.5}] * 3
        rec = ev.token_record("xyz", letters)
        self.assertEqual((rec["spelled"], rec["method"], rec["confidence"]), (True, "fingerspelling", 0.5))
        self.assertTrue(ev.token_record("vacio", [])["spelled"])


class ProperNounTests(unittest.TestCase):
    def test_mid_sentence_capitals_are_proper_nouns(self):
        forms = ev.proper_noun_forms("La isla está junto a Haití y a Puerto Rico. Hoy llueve en el Caribe.")
        self.assertEqual(forms, {"haiti", "puerto", "rico", "caribe"})

    def test_sentence_initial_capital_alone_is_not_proper(self):
        self.assertEqual(ev.proper_noun_forms("Hoy llueve. Mañana hará sol."), set())
        self.assertEqual(ev.proper_noun_forms("¿Dónde está? Aquí está."), set())

    def test_initial_capital_counts_when_also_seen_mid_sentence(self):
        forms = ev.proper_noun_forms("Haití comparte la isla. La isla incluye a Haití.")
        self.assertIn("haiti", forms)

    def test_acronyms_are_proper_even_at_sentence_start(self):
        self.assertEqual(ev.proper_noun_forms("UNESCO reconoció el merengue."), {"unesco"})

    def test_is_proper_token_needs_every_word(self):
        forms = {"puerto", "rico"}
        self.assertTrue(ev.is_proper_token("puerto", forms))
        self.assertTrue(ev.is_proper_token("puerto rico", forms))
        self.assertFalse(ev.is_proper_token("puerto seguro", forms))
        self.assertFalse(ev.is_proper_token("", forms))

    def test_count_letters(self):
        self.assertEqual(ev.count_letters([{"es_deletreo": True}] * 4 + [{"es_deletreo": False}]), 4)
        self.assertEqual(ev.count_letters([]), 0)


class ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nlp = ev.LSRDNlpEngine()
        cls.tr = ev.LSRDTranslator()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def test_morphology_provenance_survives_per_token_translation(self):
        # Regression: translating bare [token] lists dropped the hint, so every
        # resolved token was reported as 'exact'.
        seq = self.nlp.process("Él trabaja mucho")["secuencia_lsrd"]
        records = [ev.token_record(t, i) for t, i in zip(seq, ev.translate_tokens(self.tr, seq))]
        self.assertIn("morphology", {r["method"] for r in records})

    def test_per_token_methods_match_whole_sentence_translation(self):
        for text in ("Él trabaja mucho", "Buenos días, ¿cómo estás?", "Los niños estudian en la biblioteca."):
            seq = self.nlp.process(text)["secuencia_lsrd"]
            whole = [i["match_method"] for i in self.tr.translate_sequence(seq) if not i.get("es_deletreo")]
            per_token = [i["match_method"] for items in ev.translate_tokens(self.tr, seq)
                         for i in items if not i.get("es_deletreo")]
            self.assertEqual(whole, per_token, text)


class MiniCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nlp = ev.LSRDNlpEngine()
        cls.tr = ev.LSRDTranslator()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def run_corpus(self, items):
        return ev.evaluate(items, self.nlp, self.tr)

    def test_recall_precision_and_order(self):
        m = self.run_corpus([
            {"id": "a", "text": "Hola", "tags": ["x"], "expected_lemmas": ["hola"]},
            {"id": "b", "text": "Hola casa", "tags": ["x", "y"], "expected_lemmas": ["hola"]},
            {"id": "c", "text": "No tengo tiempo ahora.", "tags": ["y"],
             "expected_order": ["ahora", "tener", "no"]},
            {"id": "d", "text": "No tengo tiempo ahora.", "tags": ["y"], "expected_order": ["no", "ahora"]},
        ])
        self.assertEqual(m["gold_lemma_recall"], 1.0)
        # a: hola (expected); b: hola (expected) + casa (unexpected content sign).
        self.assertEqual((m["gold_content_signs"], m["gold_lemma_precision"]), (3, round(2 / 3, 4)))
        self.assertEqual(m["gold_unexpected_signs"], {"casa": 1})
        self.assertEqual((m["gold_order_entries"], m["gold_order_accuracy"]), (2, 0.5))
        self.assertEqual(m["gold_order_failures"], ["d"])
        self.assertEqual(m["by_tag"]["x"]["sentences"], 2)
        self.assertEqual(m["by_tag"]["x"]["gold_lemma_precision"], round(2 / 3, 4))
        self.assertEqual(m["by_tag"]["y"]["gold_order_accuracy"], 0.5)

    def test_allowed_lemmas_are_not_penalised(self):
        m = self.run_corpus([{"id": "b", "text": "Hola casa", "expected_lemmas": ["hola"],
                              "allowed_lemmas": ["casa"]}])
        self.assertEqual(m["gold_lemma_precision"], 1.0)
        self.assertEqual(m["gold_unexpected_signs"], {})

    def test_missed_lemma_lowers_recall(self):
        m = self.run_corpus([{"id": "a", "text": "Hola", "expected_lemmas": ["hola", "zzz"]}])
        self.assertEqual(m["gold_lemma_recall"], 0.5)
        self.assertEqual(m["gold_missed_lemmas"], {"zzz": 1})

    def test_fingerspelling_rate_and_oov(self):
        m = self.run_corpus([
            {"id": "a", "text": "Hola", "tags": ["t"]},
            {"id": "b", "text": "Hola qwzx", "tags": ["t"]},
        ])
        self.assertEqual(m["fingerspelled_tokens"], 1)
        self.assertIn("qwzx", m["oov_words"])
        self.assertEqual(m["match_method_counts"]["fingerspelling"], 1)
        self.assertEqual(m["avg_confidence_by_method"]["fingerspelling"], 0.5)
        per_sentence = m["fingerspelling_per_sentence"]
        self.assertEqual((per_sentence["sentences_with_fingerspelling"],
                          per_sentence["sentences_fully_lexical"]), (1, 1))
        self.assertEqual(per_sentence["max_rate"], 0.5)
        self.assertEqual(per_sentence["worst_sentences"][0]["id"], "b")
        self.assertEqual(m["by_tag"]["t"]["fingerspelling_rate"], m["fingerspelling_rate"])


class WordVersusLetterMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nlp = ev.LSRDNlpEngine()
        cls.tr = ev.LSRDTranslator()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()

    def test_proper_and_common_split(self):
        # qwzx: common word that cannot be signed; Zxqv: capitalized mid-sentence, a proper noun.
        m = ev.evaluate([{"id": "a", "text": "Hola qwzx casa Zxqv.", "tags": ["t"]}], self.nlp, self.tr)
        self.assertEqual(m["fingerspelled_tokens"], 2)
        self.assertEqual(m["fingerspelled_proper_nouns"], 1)
        self.assertEqual(m["fingerspelled_common_words"], 1)
        self.assertEqual(m["fingerspelled_letters"], 8)
        self.assertEqual(m["letters_per_lexical_sign"], round(8 / m["lexical_tokens"], 3))
        self.assertEqual(m["fingerspelled_word_rate"], m["fingerspelling_rate"])
        # Common words are every word that is not a proper noun.
        self.assertEqual(m["common_fingerspelled_word_rate"], round(1 / (m["output_tokens"] - 1), 4))
        self.assertEqual(m["proper_fingerspelled_word_rate"], 1.0)
        self.assertEqual([w["word"] for w in m["top_fingerspelled_common"]], ["qwzx"])
        self.assertEqual([w["word"] for w in m["top_fingerspelled_proper"]], ["zxqv"])
        self.assertEqual(m["by_tag"]["t"]["fingerspelled_letters"], 8)
        self.assertEqual(m["by_tag"]["t"]["fingerspelled_common_words"], 1)

    def test_no_spelling_gives_zero_rates(self):
        m = ev.evaluate([{"id": "a", "text": "Hola", "tags": ["t"]}], self.nlp, self.tr)
        self.assertEqual((m["fingerspelled_letters"], m["letters_per_lexical_sign"],
                          m["common_fingerspelled_word_rate"]), (0, 0.0, 0.0))


class RealisticCorpusTests(unittest.TestCase):
    REGISTERS = {"encyclopedic", "local_news", "school_notice", "health", "government",
                 "sports", "weather", "social"}

    @classmethod
    def setUpClass(cls):
        with open(REALISTIC_PATH, encoding="utf-8") as f:
            cls.corpus = json.load(f)["items"]

    def test_shape(self):
        self.assertGreaterEqual(len(self.corpus), 40)
        ids = [e["id"] for e in self.corpus]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({e["register"] for e in self.corpus}, self.REGISTERS)
        for e in self.corpus:
            self.assertIn(e["register"], e["tags"], e["id"])
            self.assertIsInstance(e["has_proper_nouns"], bool, e["id"])
            self.assertNotIn("expected_lemmas", e, "the realistic corpus is not a gold corpus")
            sentences = [p for p in e["text"].replace("!", ".").replace("?", ".").split(".") if p.strip()]
            self.assertTrue(2 <= len(sentences) <= 4, e["id"])

    def test_has_proper_nouns_flag_matches_detector(self):
        for e in self.corpus:
            self.assertEqual(bool(ev.proper_noun_forms(e["text"])), e["has_proper_nouns"], e["id"])
        flags = [e["has_proper_nouns"] for e in self.corpus]
        self.assertTrue(any(flags) and not all(flags))


class RealisticQualityTests(unittest.TestCase):
    """Same limits as the 'Quality gate (realistic corpus)' step of the CI."""

    @classmethod
    def setUpClass(cls):
        with open(REALISTIC_PATH, encoding="utf-8") as f:
            cls.m = ev.evaluate(json.load(f)["items"])

    def test_gate_limits(self):
        # Measured 0.7562 / 0.2303 once "y"/"a" stopped counting as the letter
        # signs Y/A and proper nouns stopped matching common words ("Mona" -> MONO).
        self.assertGreaterEqual(self.m["lexical_coverage"], 0.75)
        self.assertLessEqual(self.m["common_fingerspelled_word_rate"], 0.235)

    def test_saved_runs_show_the_improvement(self):
        data = os.path.join(_common.ROOT, "tests", "data")
        with open(os.path.join(data, "realistic_baseline.json"), encoding="utf-8") as f:
            before = json.load(f)
        with open(os.path.join(data, "realistic_after.json"), encoding="utf-8") as f:
            after = json.load(f)
        for key in ("common_fingerspelled_word_rate", "letters_per_lexical_sign"):
            self.assertLess(after[key], before[key], key)
        self.assertGreater(after["lexical_coverage"], before["lexical_coverage"])
        self.assertEqual(after["sentences"], before["sentences"])


class MultiCorpusCliTests(unittest.TestCase):
    def run_cli(self, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "m.json")
            old = sys.argv
            sys.argv = ["evaluate.py", "--quiet", "--out", out, *argv]
            try:
                ev.main()
            finally:
                sys.argv = old
            with open(out, encoding="utf-8") as f:
                return json.load(f)

    def test_single_corpus_output_is_a_plain_metrics_object(self):
        m = self.run_cli("--corpus", REALISTIC_PATH)
        self.assertNotIn("corpora", m)
        self.assertGreaterEqual(m["sentences"], 40)

    def test_several_corpora_are_reported_per_corpus(self):
        m = self.run_cli("--corpus", CORPUS_PATH, "--corpus", REALISTIC_PATH)
        self.assertEqual(list(m["corpora"]), ["eval_corpus", "eval_corpus_realistic"])
        # The top level mirrors the first corpus so existing gates keep working.
        self.assertEqual(m["sentences"], m["corpora"]["eval_corpus"]["sentences"])
        self.assertEqual(m["gold_lemma_recall"], m["corpora"]["eval_corpus"]["gold_lemma_recall"])
        self.assertGreater(m["corpora"]["eval_corpus_realistic"]["fingerspelled_letters"], 0)
        self.assertEqual(m["corpora"]["eval_corpus_realistic"]["gold_entries"], 0)


class CorpusMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CORPUS_PATH, encoding="utf-8") as f:
            cls.corpus = json.load(f)["items"]
        cls.m = ev.evaluate(cls.corpus)

    def test_corpus_is_well_formed(self):
        ids = [e["id"] for e in self.corpus]
        self.assertEqual(len(ids), len(set(ids)))
        for e in self.corpus:
            order = e.get("expected_order", [])
            self.assertEqual(len(order), len(set(order)), e["id"])
            if "allowed_lemmas" in e:
                self.assertIn("expected_lemmas", e, e["id"])
        self.assertGreaterEqual(sum(1 for e in self.corpus if e.get("expected_order")), 10)

    def test_every_method_is_reported(self):
        counts = self.m["match_method_counts"]
        self.assertEqual(sum(counts.values()), self.m["output_tokens"])
        self.assertAlmostEqual(sum(self.m["match_method_share"].values()), 1.0, places=2)
        for method in ("exact", "morphology", "fingerspelling"):
            self.assertGreater(counts.get(method, 0), 0, method)
        self.assertEqual(counts["fingerspelling"], self.m["fingerspelled_tokens"])
        self.assertEqual(set(counts), set(self.m["avg_confidence_by_method"]))

    def test_summary_is_consistent(self):
        m = self.m
        self.assertEqual(m["lexical_tokens"] + m["fingerspelled_tokens"], m["output_tokens"])
        self.assertAlmostEqual(m["lexical_coverage"] + m["fingerspelling_rate"], 1.0, places=3)
        self.assertEqual(len(m["oov_words"]), m["unique_fingerspelled_words"])
        lat = m["latency_ms"]
        self.assertLessEqual(lat["p50"], lat["p95"])
        self.assertLessEqual(lat["p95"], lat["max"])
        self.assertEqual(sum(t["sentences"] for t in m["by_tag"].values()),
                         sum(len(e.get("tags", [])) for e in self.corpus))

    def test_quality_floors(self):
        m = self.m
        self.assertGreaterEqual(m["lexical_coverage"], 0.88)
        self.assertGreaterEqual(m["gold_lemma_recall"], 0.95)
        self.assertGreaterEqual(m["gold_lemma_precision"], 0.93)
        self.assertEqual(m["gold_order_accuracy"], 1.0, m["gold_order_failures"])
        self.assertLess(m["latency_ms"]["p95"], 2000)  # thesis requirement: response under 2 s


class CheckMetricsTests(unittest.TestCase):
    GOOD = {"lexical_coverage": 0.9, "gold_lemma_recall": 0.97, "gold_lemma_precision": 0.95,
            "fingerspelling_rate": 0.1, "gold_order_accuracy": 1.0,
            "latency_ms": {"p50": 1.0, "p95": 4.0}}

    def test_defaults_pass_and_print_table(self):
        code, out = run_gate(self.GOOD)
        self.assertEqual(code, 0)
        self.assertIn("lexical_coverage", out)
        self.assertIn("PASS", out)

    def test_legacy_metrics_file_still_passes(self):
        code, _ = run_gate({"lexical_coverage": 0.9, "gold_lemma_recall": 0.97})
        self.assertEqual(code, 0)

    def test_min_coverage_and_recall_fail(self):
        self.assertEqual(run_gate({**self.GOOD, "lexical_coverage": 0.8})[0], 1)
        self.assertEqual(run_gate({**self.GOOD, "gold_lemma_recall": 0.9})[0], 1)

    def test_new_gates(self):
        self.assertEqual(run_gate(self.GOOD, "--min-precision", "0.9")[0], 0)
        self.assertEqual(run_gate(self.GOOD, "--min-precision", "0.99")[0], 1)
        self.assertEqual(run_gate(self.GOOD, "--max-fingerspelling-rate", "0.12")[0], 0)
        code, out = run_gate(self.GOOD, "--max-fingerspelling-rate", "0.05")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertEqual(run_gate(self.GOOD, "--min-order-accuracy", "1.0")[0], 0)
        self.assertEqual(run_gate(self.GOOD, "--max-p95-ms", "2")[0], 1)

    def test_common_fingerspelling_gate(self):
        good = {**self.GOOD, "common_fingerspelled_word_rate": 0.1}
        self.assertEqual(run_gate(good, "--max-common-fingerspelling-rate", "0.12")[0], 0)
        code, out = run_gate(good, "--max-common-fingerspelling-rate", "0.05")
        self.assertEqual(code, 1)
        self.assertIn("common_fingerspelling_rate", out)
        # Requested but absent from the file: unreadable input, not a silent pass.
        self.assertEqual(run_gate(self.GOOD, "--max-common-fingerspelling-rate", "0.12")[0], 2)

    def test_corpus_selection_and_no_gold_corpus(self):
        realistic = {"lexical_coverage": 0.9, "gold_entries": 0, "gold_lemmas_expected": 0,
                     "gold_lemma_recall": 0.0, "gold_lemma_precision": 0.0, "gold_order_accuracy": 0.0,
                     "common_fingerspelled_word_rate": 0.08, "latency_ms": {"p50": 1.0, "p95": 4.0}}
        multi = {**self.GOOD, "corpora": {"main": self.GOOD, "realistic": realistic}}
        # Default: the top level (first corpus), exactly as before.
        self.assertEqual(run_gate(multi)[0], 0)
        # A corpus with no gold lemmas is not failed on recall and does not print gold rows.
        code, out = run_gate(multi, "--corpus", "realistic", "--max-common-fingerspelling-rate", "0.1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("gold_lemma_recall", out)
        self.assertEqual(
            run_gate(multi, "--corpus", "realistic", "--max-common-fingerspelling-rate", "0.05")[0], 1)
        code, out = run_gate(multi, "--corpus", "missing")
        self.assertEqual(code, 2)
        self.assertIn("missing", out)

    def test_requested_gate_with_missing_metric_is_an_error(self):
        code, out = run_gate({"lexical_coverage": 0.9, "gold_lemma_recall": 0.97}, "--min-precision", "0.9")
        self.assertEqual(code, 2)
        self.assertIn("gold_lemma_precision", out)

    def test_unreadable_input(self):
        self.assertEqual(run_gate({"lexical_coverage": 0.9})[0], 2)  # recall missing
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_metrics.main(["does-not-exist.json"]), 2)


if __name__ == "__main__":
    unittest.main()
