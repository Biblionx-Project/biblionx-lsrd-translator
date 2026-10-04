import os
import re
import tempfile
import unittest
from unittest import mock

import _common
import llm_fallback
import translator


class LLMDisabledByDefaultTests(unittest.TestCase):
    def setUp(self):
        for var in ("BIBLIONX_LLM_PROVIDER", "BIBLIONX_LLM_MODEL"):
            os.environ.pop(var, None)

    def test_disabled_without_env(self):
        self.assertFalse(llm_fallback.LLMFallback.from_env().enabled)

    def test_unknown_provider_is_disabled(self):
        with mock.patch.dict(os.environ, {"BIBLIONX_LLM_PROVIDER": "nonsense"}):
            self.assertFalse(llm_fallback.LLMFallback.from_env().enabled)

    def test_known_provider_enables_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            llm = llm_fallback.LLMFallback("ollama", cache_path=os.path.join(d, "c.json"))
            self.assertTrue(llm.enabled)
            self.assertEqual(llm.calls, 0)

    def test_translator_default_never_calls_ai(self):
        tr = translator.LSRDTranslator()
        try:
            with mock.patch.object(llm_fallback.LLMFallback, "_post",
                                   side_effect=AssertionError("network call")), \
                 mock.patch.object(llm_fallback.LLMFallback, "_ask",
                                   side_effect=AssertionError("ask call")):
                out = tr.translate_sequence(["xyzqwk", "abogadoo", "casa"])
            self.assertFalse(tr.llm.enabled)
            self.assertNotIn("ai", [s["match_method"] for s in out])
        finally:
            tr.close()

    def test_no_secrets_in_source(self):
        pattern = re.compile(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,})")
        with open(os.path.join(_common.ROOT, "llm_fallback.py"), encoding="utf-8") as f:
            self.assertIsNone(pattern.search(f.read()))


if __name__ == "__main__":
    unittest.main()
