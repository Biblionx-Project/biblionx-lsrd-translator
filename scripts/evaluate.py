#!/usr/bin/env python3
"""Evaluate the LSRD translator against tests/data/eval_corpus.json.

Run from the repository root:
    python scripts/evaluate.py [--corpus PATH] [--out PATH]

Prints JSON metrics: lexical coverage, fingerspelling counts, top
fingerspelled (out-of-vocabulary) words, gold lemma recall, latency and,
when the translator exposes it, counts by match_method.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from nlp_engine import LSRDNlpEngine  # noqa: E402
from translator import LSRDTranslator  # noqa: E402


def lemma_resolved(translator, lemma, cache):
    """True if a lemma resolves to a lexical (non-fingerspelled) sign."""
    if lemma not in cache:
        items = translator.translate_sequence([lemma])
        cache[lemma] = bool(items) and not any(i.get("es_deletreo") for i in items)
    return cache[lemma]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(ROOT, "tests", "data", "eval_corpus.json"))
    ap.add_argument("--out", default=None, help="write metrics JSON to this path")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        corpus = json.load(f)["items"]

    nlp = LSRDNlpEngine()
    tr = LSRDTranslator()

    lexical = 0
    spelled_tokens = 0
    spelled_words = Counter()
    methods = Counter()
    conf_sum = 0.0
    conf_n = 0
    gold_total = 0
    gold_hit = 0
    gold_miss = Counter()
    elapsed = 0.0

    for entry in corpus:
        t0 = time.perf_counter()
        seq = nlp.process(entry["text"])["secuencia_lsrd"]
        per_token = [(tok, tr.translate_sequence([tok])) for tok in seq]
        elapsed += time.perf_counter() - t0

        resolved = set()
        for tok, items in per_token:
            if items and not any(i.get("es_deletreo") for i in items):
                lexical += 1
                resolved.add(tok)
            else:
                spelled_tokens += 1
                spelled_words[tok] += 1
            for i in items:
                m = i.get("match_method")
                if m and not i.get("es_deletreo"):
                    methods[m] += 1
                c = i.get("confidence")
                if isinstance(c, (int, float)):
                    conf_sum += c
                    conf_n += 1

        for lemma in entry.get("expected_lemmas", []):
            gold_total += 1
            if lemma in resolved or (lemma in seq and lemma_resolved(tr, lemma, {})):
                gold_hit += 1
            else:
                gold_miss[lemma] += 1

    total = lexical + spelled_tokens
    metrics = {
        "sentences": len(corpus),
        "output_tokens": total,
        "lexical_tokens": lexical,
        "lexical_coverage": round(lexical / total, 4) if total else 0.0,
        "fingerspelled_tokens": spelled_tokens,
        "unique_fingerspelled_words": len(spelled_words),
        "top_fingerspelled": [{"word": w, "count": c} for w, c in spelled_words.most_common(40)],
        "gold_entries": sum(1 for e in corpus if e.get("expected_lemmas")),
        "gold_lemmas_expected": gold_total,
        "gold_lemma_recall": round(gold_hit / gold_total, 4) if gold_total else 0.0,
        "gold_missed_lemmas": dict(gold_miss.most_common(40)),
        "avg_ms_per_sentence": round(elapsed * 1000 / len(corpus), 3) if corpus else 0.0,
    }
    if methods:
        metrics["match_method_counts"] = dict(methods)
    if conf_n:
        metrics["avg_confidence"] = round(conf_sum / conf_n, 4)

    text = json.dumps(metrics, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
