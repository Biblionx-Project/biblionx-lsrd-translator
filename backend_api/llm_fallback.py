"""Optional, low-cost AI fallback for out-of-vocabulary words.

Disabled unless BIBLIONX_LLM_PROVIDER is one of: anthropic, openai, ollama.
Keys come only from environment variables and are never logged.
The model only picks an index among dictionary candidates (max_tokens 8),
results (including negatives) are cached on disk, and any error -> None.
"""
import hashlib
import json
import os
import threading
import urllib.request

PROVIDERS = ("anthropic", "openai", "ollama")
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.2",
}
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".llm_cache.json")
TIMEOUT = 8
MAX_CANDIDATES = 12


class LLMFallback:
    def __init__(self, provider=None, model=None, max_calls=50, cache_path=CACHE_PATH):
        self.provider = provider if provider in PROVIDERS else None
        self.model = model or (DEFAULT_MODELS[self.provider] if self.provider else None)
        self.max_calls = max_calls
        self.calls = 0
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._cache = self._load_cache() if self.provider else {}

    @classmethod
    def from_env(cls):
        provider = os.environ.get("BIBLIONX_LLM_PROVIDER", "").strip().lower()
        try:
            max_calls = int(os.environ.get("BIBLIONX_LLM_MAX_CALLS", "50"))
        except ValueError:
            max_calls = 50
        model = os.environ.get("BIBLIONX_LLM_MODEL", "").strip() or None
        return cls(provider or None, model, max_calls)

    @property
    def enabled(self):
        return self.provider is not None

    # ---- cache ----
    def _load_cache(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    @staticmethod
    def _key(word, candidates):
        h = hashlib.sha1("|".join(candidates).encode("utf-8")).hexdigest()[:12]
        return f"{word}::{h}"

    # ---- public API ----
    def choose(self, word, context, candidates):
        """Return the candidate closest in meaning to `word`, or None."""
        if not self.enabled or not word or not candidates:
            return None
        cands = list(dict.fromkeys(candidates))[:MAX_CANDIDATES]
        key = self._key(word, cands)
        with self._lock:
            if key in self._cache:
                cached = self._cache[key]
                return cached if cached in cands else None
            if self.calls >= self.max_calls:
                return None
            self.calls += 1
        try:
            answer = self._ask(word, context, cands)
        except Exception:
            return None  # fail closed; transient errors are not cached
        result = self._parse(answer, cands)
        with self._lock:
            self._cache[key] = result
            self._save_cache()
        return result

    @staticmethod
    def _parse(answer, cands):
        text = (answer or "").strip().upper()
        if not text or text.startswith("NONE"):
            return None
        digits = ""
        for ch in text:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if not digits:
            return None
        idx = int(digits) - 1
        return cands[idx] if 0 <= idx < len(cands) else None

    def _prompt(self, word, context, cands):
        opts = "\n".join(f"{i}. {c}" for i, c in enumerate(cands, 1))
        ctx = (context or "")[:120]
        return (
            "Spanish (Dominican) word to map to a sign-language dictionary entry.\n"
            f"Word: {word}\nContext: {ctx}\nOptions:\n{opts}\n"
            "Reply with only the number of the option closest in meaning, or NONE."
        )

    # ---- transport ----
    def _post(self, url, payload, headers):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _ask(self, word, context, cands):
        prompt = self._prompt(word, context, cands)
        hdr = {"Content-Type": "application/json"}
        if self.provider == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not key:
                raise RuntimeError("missing key")
            hdr.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
            out = self._post("https://api.anthropic.com/v1/messages", {
                "model": self.model, "max_tokens": 8, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}, hdr)
            return out["content"][0]["text"]
        if self.provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "")
            if not key:
                raise RuntimeError("missing key")
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            hdr["Authorization"] = "Bearer " + key
            out = self._post(base + "/chat/completions", {
                "model": self.model, "max_tokens": 8, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}, hdr)
            return out["choices"][0]["message"]["content"]
        base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        out = self._post(base + "/api/chat", {
            "model": self.model, "stream": False,
            "options": {"temperature": 0, "num_predict": 8},
            "messages": [{"role": "user", "content": prompt}]}, hdr)
        return out["message"]["content"]


if __name__ == "__main__":
    fb = LLMFallback.from_env()
    if not fb.enabled:
        print("LLM fallback disabled (set BIBLIONX_LLM_PROVIDER to anthropic, openai or ollama).")
    else:
        print(f"LLM fallback enabled: provider={fb.provider} model={fb.model} max_calls={fb.max_calls}")
        print(fb.choose("galleta", "quiero una galleta", ["pan", "dulce", "casa"]))
