"""Lightweight ML fuzzy matcher for the LSRD dictionary.

Pure Python stdlib, no network. Pipeline:
  1. Character n-gram (2-4, with word boundary markers) TF-IDF vectors.
  2. Cosine similarity through an inverted index (n-gram -> postings).
  3. Rerank the top-k with normalized Damerau-Levenshtein plus a small bonus
     for the same first letter / same length band.
  4. Guards against false positives: short words never fuzzy-match, a score
     threshold and a bounded edit distance are required.
"""

import math
import re
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict

NGRAM_MIN, NGRAM_MAX = 2, 4
MIN_QUERY_LEN = 4  # words of <= 3 chars never fuzzy-match
TOP_K_RERANK = 12


def normalize(text):
    """Lowercase, strip accents, remove parentheses and extra whitespace."""
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[()\[\]]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ngrams(word):
    padded = f"^{word}$"
    out = []
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        if len(padded) < n:
            continue
        for i in range(len(padded) - n + 1):
            out.append(padded[i:i + n])
    return out


def damerau_levenshtein(a, b, max_dist=None):
    """Optimal string alignment distance (Damerau-Levenshtein, adjacent swaps)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > (max_dist if max_dist is not None else la + lb):
        return abs(la - lb)
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
        prev2, prev = prev, cur
    return prev[lb]


def _split_variants(norm):
    """Expand 'abogado, da' / 'abajo, debajo' / '(phrase)' into separate keys."""
    keys = set()
    clean = normalize(norm)
    if clean:
        keys.add(clean)
    parts = [normalize(p) for p in str(norm).split(",")]
    parts = [p for p in parts if p]
    gender_pair = (len(parts) == 2 and len(parts[1]) <= 4
                   and " " not in parts[0] and " " not in parts[1])
    # A gender suffix ('da', 'ra', 'tras') is not a word of its own: indexing it
    # made "tras" fuzzy-match NOSOTROS, TRAS. Only real alternatives
    # ('abajo, debajo') become separate keys.
    keys.update(parts[:1] if gender_pair else parts)
    if len(parts) == 2 and parts[0]:
        first, second = parts
        # Gender pair: 'abogado, da' -> 'abogada'; 'nosotros, tras' -> 'nosotras'
        if gender_pair:
            variants = {first[:-len(second)] + second}
            if second[0] == first[-1]:
                variants.add(first + second[1:])
            if len(second) == 1:
                variants.add(first + second)
            keys.update(v for v in variants if len(v) >= 3)
    return keys


class FuzzyMatcher:
    def __init__(self, entries):
        """entries: iterable of (norm, palabra_id)."""
        self.keys = []          # distinct normalized keys
        self.key_ids = []       # palabra_id per key
        seen = {}
        for norm, pid in entries:
            for key in _split_variants(norm):
                if key in seen:
                    continue
                seen[key] = len(self.keys)
                self.keys.append(key)
                self.key_ids.append(pid)
        n_docs = len(self.keys)
        df = defaultdict(int)
        doc_grams = []
        for key in self.keys:
            grams = defaultdict(int)
            for g in ngrams(key):
                grams[g] += 1
            doc_grams.append(grams)
            for g in grams:
                df[g] += 1
        self.idf = {g: math.log((1 + n_docs) / (1 + c)) + 1.0 for g, c in df.items()}
        self.index = defaultdict(list)  # gram -> [(doc, weight)]
        for doc, grams in enumerate(doc_grams):
            weights = {g: (1 + math.log(c)) * self.idf[g] for g, c in grams.items()}
            norm_len = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            for g, w in weights.items():
                self.index[g].append((doc, w / norm_len))
        self.exact = {k: i for i, k in enumerate(self.keys)}

    @classmethod
    def from_db(cls, db_path):
        conn = sqlite3.connect(db_path)
        try:
            entries = list(conn.execute("SELECT palabra_norm, id FROM palabras"))
            try:
                entries += [(s, pid) for pid, s in conn.execute(
                    "SELECT palabra_id, sinonimo_norm FROM sinonimos_mapeo")]
            except sqlite3.Error:
                pass
        finally:
            conn.close()
        return cls([e for e in entries if e[0]])

    def _cosine_top(self, word, k):
        grams = defaultdict(int)
        for g in ngrams(word):
            grams[g] += 1
        weights = {g: (1 + math.log(c)) * self.idf[g] for g, c in grams.items() if g in self.idf}
        if not weights:
            return []
        qnorm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        scores = defaultdict(float)
        for g, w in weights.items():
            qw = w / qnorm
            for doc, dw in self.index[g]:
                scores[doc] += qw * dw
        return sorted(scores.items(), key=lambda x: -x[1])[:k]

    @staticmethod
    def _rerank_score(word, key, cosine):
        longest = max(len(word), len(key))
        dist = damerau_levenshtein(word, key)
        sim = 1.0 - dist / longest
        score = 0.65 * sim + 0.35 * cosine
        if word[0] == key[0]:
            score += 0.03
        if abs(len(word) - len(key)) <= 1:
            score += 0.02
        return min(score, 1.0), dist

    def candidates(self, word, k=5):
        word = normalize(word)
        if len(word) < MIN_QUERY_LEN:
            return []
        out = []
        for doc, cos in self._cosine_top(word, max(k, TOP_K_RERANK)):
            key = self.keys[doc]
            score, dist = self._rerank_score(word, key, cos)
            out.append({"palabra_id": self.key_ids[doc], "norm": key,
                        "score": round(score, 4), "distance": dist})
        out.sort(key=lambda c: (-c["score"], c["distance"]))
        return out[:k]

    def match(self, word, min_score=0.84):
        word = normalize(word)
        if len(word) < MIN_QUERY_LEN:
            return None
        if word in self.exact:
            i = self.exact[word]
            return {"palabra_id": self.key_ids[i], "norm": word, "score": 1.0}
        max_dist = max(1, len(word) // 4)
        for cand in self.candidates(word, k=TOP_K_RERANK):
            if cand["score"] >= min_score and cand["distance"] <= max_dist:
                return {"palabra_id": cand["palabra_id"], "norm": cand["norm"],
                        "score": cand["score"]}
        return None


if __name__ == "__main__":
    import os
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "lsrd_dictionary.db")
    t0 = time.perf_counter()
    matcher = FuzzyMatcher.from_db(db)
    print(f"build: {(time.perf_counter() - t0) * 1000:.1f} ms, {len(matcher.keys)} keys")
    tests = ["profesorr", "biblioteka", "escuelas", "abogada", "casa", "xyz", "zapatoss"]
    total = 0.0
    for w in tests:
        t = time.perf_counter()
        res = matcher.match(w)
        dt = (time.perf_counter() - t) * 1000
        total += dt
        print(f"{w:12s} -> {res}  ({dt:.2f} ms)")
    print(f"avg latency: {total / len(tests):.2f} ms/query")
