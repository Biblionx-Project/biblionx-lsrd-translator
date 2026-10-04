"""Optional, low-cost AI fallback for out-of-vocabulary words.

Disabled unless BIBLIONX_LLM_PROVIDER is one of: anthropic, openai, ollama.
Keys come only from environment variables and are never logged.
The model only picks an index among dictionary candidates (max_tokens 8),
results (including negatives) are cached on disk, and any error -> None.

Cost guards (all optional, configured through environment variables):
  BIBLIONX_LLM_MAX_CALLS     total model calls per process; 0 = unlimited (default)
  BIBLIONX_LLM_RATE_PER_MIN  process-wide sliding-window cap; 0 = off (default)
Cached answers never count against either limit.
"""
import hashlib
import json
import os
import threading
import time
import urllib.request
from collections import deque

PROVIDERS = ("anthropic", "openai", "ollama")
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.2",
}
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".llm_cache.json")
TIMEOUT = 8
MAX_CANDIDATES = 12
RATE_WINDOW = 60.0  # seconds
LOCK_STALE = 10.0   # seconds before a leftover cache lock file is ignored


def _env_int(name, default=0):
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


class LLMFallback:
    def __init__(self, provider=None, model=None, max_calls=0, cache_path=CACHE_PATH,
                 rate_per_min=0):
        self.provider = provider if provider in PROVIDERS else None
        self.model = model or (DEFAULT_MODELS[self.provider] if self.provider else None)
        self.max_calls = max(0, int(max_calls or 0))        # 0 = unlimited
        self.rate_per_min = max(0, int(rate_per_min or 0))  # 0 = off
        self.calls = 0
        self.rate_blocked = 0
        self._stamps = deque()
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._cache = self._load_cache() if self.provider else {}

    @classmethod
    def from_env(cls):
        provider = os.environ.get("BIBLIONX_LLM_PROVIDER", "").strip().lower()
        max_calls = _env_int("BIBLIONX_LLM_MAX_CALLS", 0)
        rate = _env_int("BIBLIONX_LLM_RATE_PER_MIN", 0)
        model = os.environ.get("BIBLIONX_LLM_MODEL", "").strip() or None
        return cls(provider or None, model, max_calls, rate_per_min=rate)

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

    def _acquire_file_lock(self, timeout=2.0):
        """Tiny cross-process lock (O_EXCL lock file). Returns its path or None."""
        lock = self.cache_path + ".lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return lock
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock) > LOCK_STALE:
                        os.remove(lock)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.01)
            except OSError:
                return None

    def _save_cache(self):
        """Merge with the on-disk cache, write a temp file, atomically replace."""
        lock = None
        tmp = "%s.%d.%d.tmp" % (self.cache_path, os.getpid(), threading.get_ident())
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            lock = self._acquire_file_lock()
            merged = self._load_cache()
            merged.update(self._cache)
            self._cache = merged
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
        finally:
            if lock:
                try:
                    os.remove(lock)
                except OSError:
                    pass

    @staticmethod
    def _key(word, candidates):
        h = hashlib.sha1("|".join(candidates).encode("utf-8")).hexdigest()[:12]
        return f"{word}::{h}"

    def _allow_call(self):
        """Reserve a model call if limits permit. Caller must hold self._lock."""
        if self.max_calls and self.calls >= self.max_calls:
            return False
        if self.rate_per_min:
            now = time.monotonic()
            while self._stamps and now - self._stamps[0] >= RATE_WINDOW:
                self._stamps.popleft()
            if len(self._stamps) >= self.rate_per_min:
                self.rate_blocked += 1
                return False
            self._stamps.append(now)
        self.calls += 1
        return True

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
            if not self._allow_call():
                return None
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
        print(f"LLM fallback enabled: provider={fb.provider} model={fb.model} "
              f"max_calls={fb.max_calls or 'unlimited'} rate_per_min={fb.rate_per_min or 'off'}")
        print(fb.choose("galleta", "quiero una galleta", ["pan", "dulce", "casa"]))
