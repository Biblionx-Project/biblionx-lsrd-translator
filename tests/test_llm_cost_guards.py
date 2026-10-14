import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import _common  # noqa: F401
import llm_fallback

CANDS = ["pan", "dulce", "casa"]


def make(d, **kw):
    return llm_fallback.LLMFallback("ollama", cache_path=os.path.join(d, "c.json"), **kw)


class LimitTests(unittest.TestCase):
    def test_defaults_unlimited_and_rate_off(self):
        with mock.patch.dict(os.environ, {"BIBLIONX_LLM_PROVIDER": "ollama"}):
            os.environ.pop("BIBLIONX_LLM_MAX_CALLS", None)
            os.environ.pop("BIBLIONX_LLM_RATE_PER_MIN", None)
            fb = llm_fallback.LLMFallback.from_env()
        self.assertEqual((fb.max_calls, fb.rate_per_min), (0, 0))

    def test_unlimited_makes_many_calls(self):
        with tempfile.TemporaryDirectory() as d:
            fb = make(d)
            with mock.patch.object(fb, "_ask", return_value="1") as ask:
                for i in range(200):
                    self.assertEqual(fb.choose("w%d" % i, "", CANDS), "pan")
            self.assertEqual(ask.call_count, 200)

    def test_max_calls_still_configurable(self):
        with tempfile.TemporaryDirectory() as d:
            fb = make(d, max_calls=2)
            with mock.patch.object(fb, "_ask", return_value="1") as ask:
                res = [fb.choose("w%d" % i, "", CANDS) for i in range(4)]
            self.assertEqual(res, ["pan", "pan", None, None])
            self.assertEqual(ask.call_count, 2)

    def test_rate_limiter_blocks_then_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            fb = make(d, rate_per_min=3)
            with mock.patch.object(fb, "_ask", return_value="2") as ask:
                res = [fb.choose("w%d" % i, "", CANDS) for i in range(5)]
                self.assertEqual(res, ["dulce"] * 3 + [None] * 2)
                self.assertEqual(ask.call_count, 3)
                self.assertEqual(fb.rate_blocked, 2)
                # cached words still answer while rate-limited
                self.assertEqual(fb.choose("w0", "", CANDS), "dulce")
                # the window slides
                later = llm_fallback.time.monotonic() + 61
                with mock.patch.object(llm_fallback.time, "monotonic", return_value=later):
                    self.assertEqual(fb.choose("w9", "", CANDS), "dulce")

    def test_env_parsing(self):
        env = {"BIBLIONX_LLM_PROVIDER": "ollama", "BIBLIONX_LLM_MAX_CALLS": "x",
               "BIBLIONX_LLM_RATE_PER_MIN": "30"}
        with mock.patch.dict(os.environ, env):
            fb = llm_fallback.LLMFallback.from_env()
        self.assertEqual((fb.max_calls, fb.rate_per_min), (0, 30))

    def test_never_called_without_provider(self):
        with mock.patch.object(llm_fallback.LLMFallback, "_post",
                               side_effect=AssertionError("network")):
            fb = llm_fallback.LLMFallback(None, rate_per_min=5)
            self.assertIsNone(fb.choose("galleta", "", CANDS))

    def test_never_called_without_key(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {}), \
                mock.patch.object(llm_fallback.LLMFallback, "_post",
                                  side_effect=AssertionError("network")):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            fb = llm_fallback.LLMFallback("anthropic", cache_path=os.path.join(d, "c.json"))
            self.assertIsNone(fb.choose("galleta", "", CANDS))


class CacheTests(unittest.TestCase):
    def test_atomic_write_leaves_valid_json_no_temp(self):
        with tempfile.TemporaryDirectory() as d:
            fb = make(d)
            with mock.patch.object(fb, "_ask", return_value="3"):
                fb.choose("galleta", "", CANDS)
            with open(fb.cache_path, encoding="utf-8") as f:
                self.assertIn("casa", json.load(f).values())
            self.assertEqual(sorted(os.listdir(d)), ["c.json"])

    def test_concurrent_threads_do_not_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as d:
            fb = make(d)
            with mock.patch.object(fb, "_ask", return_value="1"):
                ts = [threading.Thread(target=lambda i=i: fb.choose("w%d" % i, "", CANDS))
                      for i in range(40)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
            with open(fb.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data), 40)
            self.assertEqual(fb.calls, 40)
            self.assertEqual(sorted(os.listdir(d)), ["c.json"])

    def test_two_instances_merge(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = make(d), make(d)
            with mock.patch.object(a, "_ask", return_value="1"), \
                    mock.patch.object(b, "_ask", return_value="2"):
                a.choose("uno", "", CANDS)
                b.choose("dos", "", CANDS)
            with open(a.cache_path, encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)), 2)


if __name__ == "__main__":
    unittest.main()
