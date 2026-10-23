"""Semantic AI fallback: whole-dictionary prompt, validation, caching, guards.

The HTTP layer (LLMFallback._post) is always mocked; nothing here touches the
network or a real API key.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import _common  # noqa: F401
import llm_fallback
import translator

VOCAB = ["lluvia", "casa", "centro", "pueblo", "abajo, debajo", "casa", "recomendacion"]
FAKE_KEY = "test-key-not-real"


def anthropic_reply(text, **usage):
    return {"content": [{"type": "text", "text": text}], "usage": usage}


def openai_reply(text):
    return {"choices": [{"message": {"content": text}}]}


def make(d, provider="anthropic", **kw):
    return llm_fallback.LLMFallback(provider, cache_path=os.path.join(d, "c.json"), **kw)


def fresh(provider="anthropic", **kw):
    """An instance with its own throw-away cache directory."""
    tmp = tempfile.TemporaryDirectory()
    fb = make(tmp.name, provider, **kw)
    fb._tmp = tmp  # keep the directory alive as long as the instance
    return fb


class SemanticBase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": FAKE_KEY, "OPENAI_API_KEY": FAKE_KEY})
        self._env.start()
        self.addCleanup(self._env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = self._tmp.name


class PromptTests(SemanticBase):
    def test_anthropic_request_has_cached_vocabulary_block(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("lluvia")) as post:
            self.assertEqual(fb.choose_semantic("llover", "hoy va a llover", VOCAB), "lluvia")
        url, payload, headers = post.call_args[0][:3]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(payload["model"], "claude-haiku-4-5")
        self.assertEqual(payload["temperature"], 0)
        self.assertLessEqual(payload["max_tokens"], 32)
        system = payload["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        lines = system[0]["text"].splitlines()
        for lemma in set(VOCAB):
            self.assertIn(lemma, lines)
        # the volatile part (word + sentence) is NOT in the cached block
        self.assertNotIn("llover", system[0]["text"])
        user = payload["messages"][0]["content"]
        self.assertIn("llover", user)
        self.assertIn("hoy va a llover", user)
        self.assertEqual(headers["x-api-key"], FAKE_KEY)
        self.assertNotIn(FAKE_KEY, json.dumps(payload))

    def test_vocabulary_is_deduplicated_sorted_and_stable(self):
        fb = make(self.d)
        fb.set_vocabulary(VOCAB)
        self.assertEqual(list(fb.vocabulary), sorted(set(VOCAB)))
        first = fb._vocab_block
        fb2 = make(self.d)
        fb2.set_vocabulary(list(reversed(VOCAB)))
        self.assertEqual(fb2._vocab_block, first)  # byte-identical -> cache hits
        self.assertEqual(first.count("\ncasa\n"), 1)

    def test_system_block_identical_across_words(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("NONE")) as post:
            fb.choose_semantic("uno", "ctx a", VOCAB)
            fb.choose_semantic("dos", "ctx b")
        a, b = (c[0][1]["system"] for c in post.call_args_list)
        self.assertEqual(a, b)

    def test_openai_and_ollama_send_vocabulary_without_cache_control(self):
        for provider, reply in (("openai", openai_reply("lluvia")),
                                ("ollama", {"message": {"content": "lluvia"}})):
            with self.subTest(provider=provider):
                fb = fresh(provider)
                with mock.patch.object(fb, "_post", return_value=reply) as post:
                    self.assertEqual(fb.choose_semantic("llover", "ctx", VOCAB), "lluvia")
                payload = post.call_args[0][1]
                self.assertNotIn("cache_control", json.dumps(payload))
                self.assertEqual(payload["messages"][0]["role"], "system")
                self.assertIn("pueblo", payload["messages"][0]["content"])
                self.assertIn("llover", payload["messages"][1]["content"])
        # ollama needs a context window large enough for the vocabulary
        self.assertGreaterEqual(payload["options"]["num_ctx"], 8192)

    def test_usage_counters_are_tracked(self):
        fb = make(self.d)
        reply = anthropic_reply("casa", cache_read_input_tokens=7000, input_tokens=20)
        with mock.patch.object(fb, "_post", return_value=reply):
            fb.choose_semantic("hogar", "ctx", VOCAB)
        self.assertEqual(fb.usage["cache_read_input_tokens"], 7000)


class ValidationTests(SemanticBase):
    def ask(self, answer, word="palabra"):
        fb = fresh()
        with mock.patch.object(fb, "_post", return_value=anthropic_reply(answer)):
            return fb.choose_semantic(word, "", VOCAB)

    def test_valid_lemma_accepted_with_noise(self):
        self.assertEqual(self.ask("casa"), "casa")
        self.assertEqual(self.ask('  "Casa".  '), "casa")
        self.assertEqual(self.ask("abajo, debajo"), "abajo, debajo")
        self.assertEqual(self.ask("casa\nporque es un lugar"), "casa")

    def test_accent_insensitive(self):
        self.assertEqual(self.ask("recomendación"), "recomendacion")

    def test_invented_lemma_rejected(self):
        self.assertIsNone(self.ask("ubicar"))
        self.assertIsNone(self.ask("I think the lemma is casa"))

    def test_none_and_empty_answers(self):
        self.assertIsNone(self.ask("NONE"))
        self.assertIsNone(self.ask("none."))
        self.assertIsNone(self.ask(""))

    def test_malformed_response_fails_closed_and_is_not_cached(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value={"unexpected": 1}) as post:
            self.assertIsNone(fb.choose_semantic("hogar", "", VOCAB))
            self.assertIsNone(fb.choose_semantic("hogar", "", VOCAB))
        self.assertEqual(post.call_count, 2)  # errors are retried, not cached

    def test_no_vocabulary_no_call(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", side_effect=AssertionError("network")):
            self.assertIsNone(fb.choose_semantic("hogar", ""))

    def test_missing_key_makes_no_request(self):
        fb = make(self.d)
        with mock.patch.dict(os.environ, {}), \
                mock.patch.object(fb, "_post", side_effect=AssertionError("network")):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertIsNone(fb.choose_semantic("hogar", "", VOCAB))

    def test_disabled_provider_never_calls(self):
        fb = llm_fallback.LLMFallback(None, cache_path=os.path.join(self.d, "c.json"))
        with mock.patch.object(fb, "_post", side_effect=AssertionError("network")):
            self.assertIsNone(fb.choose_semantic("hogar", "", VOCAB))


class CacheAndGuardTests(SemanticBase):
    def test_cache_hit_avoids_second_call(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("lluvia")) as post:
            self.assertEqual(fb.choose_semantic("llover", "va a llover", VOCAB), "lluvia")
            self.assertEqual(fb.choose_semantic("llover", "va a llover", VOCAB), "lluvia")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(fb.calls, 1)

    def test_negative_answer_is_cached(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("NONE")) as post:
            self.assertIsNone(fb.choose_semantic("haiti", "ctx", VOCAB))
            self.assertIsNone(fb.choose_semantic("haiti", "ctx", VOCAB))
        self.assertEqual(post.call_count, 1)

    def test_cache_persists_to_disk_across_instances(self):
        a = make(self.d)
        with mock.patch.object(a, "_post", return_value=anthropic_reply("casa")):
            a.choose_semantic("hogar", "ctx", VOCAB)
        b = make(self.d)
        with mock.patch.object(b, "_post", side_effect=AssertionError("network")):
            self.assertEqual(b.choose_semantic("hogar", "ctx", VOCAB), "casa")
        with open(a.cache_path, encoding="utf-8") as f:
            self.assertNotIn(FAKE_KEY, f.read())

    def test_different_context_is_a_different_cache_entry(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("casa")) as post:
            fb.choose_semantic("hogar", "una casa grande", VOCAB)
            fb.choose_semantic("hogar", "otra frase distinta", VOCAB)
            fb.choose_semantic("hogar", "  UNA casa   grande ", VOCAB)  # same after folding
        self.assertEqual(post.call_count, 2)

    def test_changed_vocabulary_invalidates_cache(self):
        fb = make(self.d)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("casa")) as post:
            fb.choose_semantic("hogar", "ctx", VOCAB)
            fb.choose_semantic("hogar", "ctx", VOCAB + ["hogar"])
        self.assertEqual(post.call_count, 2)

    def test_stale_cached_lemma_not_in_vocabulary_is_ignored(self):
        fb = make(self.d)
        fb.set_vocabulary(VOCAB)
        fb._cache[fb._semantic_key("hogar", "ctx")] = "inventada"
        with mock.patch.object(fb, "_post", side_effect=AssertionError("network")):
            self.assertIsNone(fb.choose_semantic("hogar", "ctx"))

    def test_max_calls_guard(self):
        fb = make(self.d, max_calls=2)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("casa")) as post:
            res = [fb.choose_semantic("w%d" % i, "", VOCAB) for i in range(4)]
            self.assertEqual(fb.choose_semantic("w0", "", VOCAB), "casa")  # cached, free
        self.assertEqual(res, ["casa", "casa", None, None])
        self.assertEqual(post.call_count, 2)

    def test_rate_guard(self):
        fb = make(self.d, rate_per_min=1)
        with mock.patch.object(fb, "_post", return_value=anthropic_reply("casa")) as post:
            res = [fb.choose_semantic("w%d" % i, "", VOCAB) for i in range(3)]
        self.assertEqual(res, ["casa", None, None])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(fb.rate_blocked, 2)


class TranslatorSemanticTests(SemanticBase):
    @classmethod
    def setUpClass(cls):
        # build the (shared, read-only) index once with no AI configured
        cls.probe = translator.LSRDTranslator()
        cls.lemmas = cls.probe._index.lemmas

    @classmethod
    def tearDownClass(cls):
        cls.probe.close()

    def setUp(self):
        super().setUp()
        self.fb = make(self.d)
        self.tr = translator.LSRDTranslator(llm=self.fb)
        self.addCleanup(self.tr.close)

    def test_vocabulary_sent_is_the_dictionary_lemmas(self):
        self.assertGreater(len(self.lemmas), 2000)
        self.assertIn("casa", self.lemmas)
        with mock.patch.object(self.fb, "_post", return_value=anthropic_reply("NONE")) as post:
            self.tr.translate_sequence(["xyzqwk"], context="una frase")
        text = post.call_args[0][1]["system"][0]["text"]
        self.assertTrue(set(self.lemmas) <= set(text.splitlines()))

    def test_ai_match_is_a_real_sign_capped_confidence(self):
        with mock.patch.object(self.fb, "_post", return_value=anthropic_reply("casa")) as post:
            out = self.tr.translate_sequence(["xyzqwk"], context="vivo en xyzqwk")
        self.assertEqual(len(out), 1)
        sign = out[0]
        self.assertEqual(sign["match_method"], "ai")
        self.assertEqual(sign["matched_norm"], "casa")
        self.assertLessEqual(sign["confidence"], 0.6)
        self.assertFalse(sign["es_deletreo"])
        self.assertTrue(sign["id"].startswith("lsrd_"))
        self.assertEqual(post.call_count, 1)

    def test_none_falls_through_to_fingerspelling_with_spelled_fields(self):
        with mock.patch.object(self.fb, "_post", return_value=anthropic_reply("NONE")):
            out = self.tr.translate_sequence(["xyzqwk"])
        self.assertTrue(all(s["match_method"] == "fingerspelling" for s in out))
        self.assertEqual({s["spelled_word"] for s in out}, {"xyzqwk"})

    def test_invented_answer_falls_through_to_fingerspelling(self):
        with mock.patch.object(self.fb, "_post", return_value=anthropic_reply("inventado")):
            out = self.tr.translate_sequence(["xyzqwk"])
        self.assertTrue(all(s["es_deletreo"] for s in out))

    def test_exact_and_fuzzy_come_first(self):
        with mock.patch.object(self.fb, "_post", side_effect=AssertionError("network")):
            self.assertEqual(self.tr.translate_sequence(["casa"])[0]["match_method"], "exact")
            self.assertEqual(self.tr.translate_sequence(["abogadoo"])[0]["match_method"], "fuzzy")

    def test_short_and_numeric_tokens_never_reach_the_model(self):
        with mock.patch.object(self.fb, "_post", side_effect=AssertionError("network")):
            out = self.tr.translate_sequence(["lo", "x9z"])
        self.assertTrue(all(s["es_deletreo"] for s in out))

    def test_repeated_word_in_same_context_costs_one_call(self):
        with mock.patch.object(self.fb, "_post", return_value=anthropic_reply("casa")) as post:
            seq = self.tr.translate_sequence(["xyzqwk", "xyzqwk"], context="ctx")
        self.assertEqual([s["match_method"] for s in seq], ["ai", "ai"])
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
