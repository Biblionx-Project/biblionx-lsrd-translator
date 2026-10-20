#!/usr/bin/env python3
"""Evaluate the LSRD translator against tests/data/eval_corpus.json.

Run from the repository root:
    python scripts/evaluate.py [--corpus PATH] [--out PATH] [--quiet]

Prints JSON metrics (also written to --out). The evaluation never calls an AI
provider: the BIBLIONX_LLM_* environment variables are ignored so results are
deterministic and free.

Metric groups (names follow the quality vocabulary of the project thesis:
linguistic precision, coverage, response time):

* Coverage: ``lexical_coverage`` (tokens resolved to a dictionary sign),
  ``fingerspelling_rate`` (1 - coverage), OOV words, and the rate per sentence.
* Provenance: ``match_method`` distribution over every output token
  (exact, morphology, phrase, synonym, curated_synonym, fuzzy, ai,
  fingerspelling) with the average confidence of each method.
* Gold quality (entries with ``expected_lemmas``): lemma recall, lemma
  precision over content signs (extra unexpected signs lower it) and, for
  entries with ``expected_order``, sequence order accuracy.
* ``by_tag``: the same figures split by corpus tag.
* ``latency_ms``: p50/p95/max of one sentence end to end (NLP + translation).

Corpus entry fields: ``id``, ``text``, ``tags``; optional ``expected_lemmas``
(content lemmas that must be resolved to signs), ``allowed_lemmas`` (extra
content signs that are acceptable and not counted against precision) and
``expected_order`` (lemmas whose relative order in the output is fixed by the
LSRD rules of grammar.py: TIME first, NEGATION last).
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# Deterministic and free: never reach an AI provider while evaluating.
for _var in ("BIBLIONX_LLM_PROVIDER", "BIBLIONX_LLM_MODEL", "BIBLIONX_LLM_MAX_CALLS"):
    os.environ.pop(_var, None)

import grammar  # noqa: E402
from nlp_engine import LSRDNlpEngine, TokenSequence  # noqa: E402
from translator import LSRDTranslator  # noqa: E402

METRICS_VERSION = 2

# Structural words that are real signs but carry no lexical content: they are
# left out of the precision denominator so only content signs are judged.
FUNCTION_WORDS = frozenset({
    "yo", "tu", "el", "ella", "usted", "ustedes", "nosotros", "nosotras", "ellos", "ellas",
    "me", "te", "se", "nos", "le", "lo", "la", "les", "mi", "mis", "tus", "su", "sus",
    "y", "o", "a", "e", "u", "en", "de", "con", "por", "para", "sin", "al", "del",
}) | grammar.NEGATION_WORDS | grammar.QUESTION_WORDS


def percentile(values, pct):
    """Linear-interpolated percentile (0-100) of a list of numbers; 0.0 if empty."""
    if not values:
        return 0.0
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    rank = (len(data) - 1) * pct / 100.0
    lo, hi = math.floor(rank), math.ceil(rank)
    return float(data[lo] + (data[hi] - data[lo]) * (rank - lo))


def ratio(num, den, digits=4):
    return round(num / den, digits) if den else 0.0


def order_score(sequence, expected_order):
    """Score the relative order of ``expected_order`` lemmas inside ``sequence``.

    Returns ``(exact_ok, pairs_ok, pairs_total)``. A lemma missing from the
    sequence fails the entry (all of its pairs count as wrong). The first
    occurrence of each lemma is used.
    """
    pairs_total = len(expected_order) * (len(expected_order) - 1) // 2
    positions = []
    for lemma in expected_order:
        try:
            positions.append(sequence.index(lemma))
        except ValueError:
            positions.append(None)
    pairs_ok = 0
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            if positions[i] is not None and positions[j] is not None and positions[i] < positions[j]:
                pairs_ok += 1
    return pairs_ok == pairs_total and pairs_total > 0, pairs_ok, pairs_total


def translate_tokens(translator, sequence):
    """Translate each token of a TokenSequence keeping its provenance.

    Each token is translated as a one-element TokenSequence that carries the
    token's own method hint ('phrase' / 'morphology') and the sentence
    context, so the match_method matches what translate_sequence(sequence)
    produces on the whole sentence. (Passing a bare ``[token]`` list drops the
    hint and every resolved token would be reported as 'exact'.)
    """
    methods = getattr(sequence, "methods", None) or ["exact"] * len(sequence)
    context = getattr(sequence, "context", "")
    return [translator.translate_sequence(TokenSequence([tok], [methods[i]], context))
            for i, tok in enumerate(sequence)]


def token_record(token, items):
    """Summarise the sign items produced for one token."""
    spelled = (not items) or any(i.get("es_deletreo") for i in items)
    method = "fingerspelling" if spelled else (items[0].get("match_method") or "exact")
    confs = [i["confidence"] for i in items if isinstance(i.get("confidence"), (int, float))]
    return {
        "token": token,
        "spelled": spelled,
        "method": method,
        "confidence": sum(confs) / len(confs) if confs else None,
    }


class Group:
    """Accumulates the figures reported for the whole corpus and for each tag."""

    def __init__(self):
        self.sentences = 0
        self.tokens = 0
        self.lexical = 0
        self.rates = []
        self.conf_sum = 0.0
        self.conf_n = 0
        self.gold_entries = 0
        self.recall_total = 0
        self.recall_hit = 0
        self.content_signs = 0
        self.content_expected = 0
        self.order_entries = 0
        self.order_ok = 0
        self.pairs_ok = 0
        self.pairs_total = 0

    def add(self, rec):
        self.sentences += 1
        self.tokens += rec["tokens"]
        self.lexical += rec["lexical"]
        self.rates.append(rec["fs_rate"])
        self.conf_sum += rec["conf_sum"]
        self.conf_n += rec["conf_n"]
        self.recall_total += rec["recall_total"]
        self.recall_hit += rec["recall_hit"]
        if rec["recall_total"]:
            self.gold_entries += 1
        self.content_signs += rec["content_signs"]
        self.content_expected += rec["content_expected"]
        if rec["order"] is not None:
            ok, p_ok, p_total = rec["order"]
            self.order_entries += 1
            self.order_ok += int(ok)
            self.pairs_ok += p_ok
            self.pairs_total += p_total

    def as_dict(self):
        out = {
            "sentences": self.sentences,
            "output_tokens": self.tokens,
            "lexical_coverage": ratio(self.lexical, self.tokens),
            "fingerspelling_rate": ratio(self.tokens - self.lexical, self.tokens),
            "mean_sentence_fingerspelling_rate": round(sum(self.rates) / len(self.rates), 4) if self.rates else 0.0,
            "avg_confidence": round(self.conf_sum / self.conf_n, 4) if self.conf_n else 0.0,
        }
        if self.gold_entries:
            out["gold_entries"] = self.gold_entries
            out["gold_lemma_recall"] = ratio(self.recall_hit, self.recall_total)
            out["gold_lemma_precision"] = ratio(self.content_expected, self.content_signs)
        if self.order_entries:
            out["gold_order_entries"] = self.order_entries
            out["gold_order_accuracy"] = ratio(self.order_ok, self.order_entries)
        return out


def evaluate(corpus, nlp=None, translator=None):
    """Run the whole evaluation and return the metrics dict."""
    nlp = nlp or LSRDNlpEngine()
    owns_translator = translator is None
    translator = translator or LSRDTranslator()

    # Warm-up so index/cache building does not distort the latency figures.
    translator.translate_sequence(nlp.process("Hola")["secuencia_lsrd"])

    overall = Group()
    by_tag = defaultdict(Group)
    method_counts = Counter()
    method_conf = defaultdict(lambda: [0.0, 0])
    oov = Counter()
    unexpected = Counter()
    order_failures = []
    missed = Counter()
    latencies = []
    sentence_rates = []
    spelled_sentences = 0

    for entry in corpus:
        t0 = time.perf_counter()
        seq = nlp.process(entry["text"])["secuencia_lsrd"]
        translator.translate_sequence(seq)
        latencies.append((time.perf_counter() - t0) * 1000.0)

        records = [token_record(tok, items)
                   for tok, items in zip(seq, translate_tokens(translator, seq))]
        total = len(records)
        spelled = sum(1 for r in records if r["spelled"])
        lexical = total - spelled
        fs_rate = spelled / total if total else 0.0
        if spelled:
            spelled_sentences += 1
        sentence_rates.append((entry.get("id", ""), fs_rate))

        conf_sum = conf_n = 0
        for r in records:
            method_counts[r["method"]] += 1
            if r["confidence"] is not None:
                method_conf[r["method"]][0] += r["confidence"]
                method_conf[r["method"]][1] += 1
                conf_sum += r["confidence"]
                conf_n += 1
            if r["spelled"]:
                oov[r["token"]] += 1

        resolved = {r["token"] for r in records if not r["spelled"]}
        expected = entry.get("expected_lemmas", [])
        hit = 0
        for lemma in expected:
            if lemma in resolved:
                hit += 1
            else:
                missed[lemma] += 1

        content_signs = content_expected = 0
        if expected:
            allowed = set(expected) | set(entry.get("allowed_lemmas", []))
            for r in records:
                if r["spelled"] or r["token"] in FUNCTION_WORDS:
                    continue
                content_signs += 1
                if r["token"] in allowed:
                    content_expected += 1
                else:
                    unexpected[r["token"]] += 1

        order = None
        if entry.get("expected_order"):
            order = order_score(list(seq), entry["expected_order"])
            if not order[0]:
                order_failures.append(entry.get("id", entry["text"]))

        rec = {
            "tokens": total, "lexical": lexical, "fs_rate": fs_rate,
            "conf_sum": conf_sum, "conf_n": conf_n,
            "recall_total": len(expected), "recall_hit": hit,
            "content_signs": content_signs, "content_expected": content_expected,
            "order": order,
        }
        overall.add(rec)
        for tag in entry.get("tags", []):
            by_tag[tag].add(rec)

    gold = overall
    total_tokens = overall.tokens
    metrics = {
        "metrics_version": METRICS_VERSION,
        "sentences": overall.sentences,
        "output_tokens": total_tokens,
        "lexical_tokens": overall.lexical,
        "lexical_coverage": ratio(overall.lexical, total_tokens),
        "fingerspelled_tokens": total_tokens - overall.lexical,
        "fingerspelling_rate": ratio(total_tokens - overall.lexical, total_tokens),
        "unique_fingerspelled_words": len(oov),
        "top_fingerspelled": [{"word": w, "count": c} for w, c in oov.most_common(40)],
        "oov_words": [w for w, _ in sorted(oov.items(), key=lambda kv: (-kv[1], kv[0]))],
        "fingerspelling_per_sentence": {
            "mean_rate": round(sum(r for _, r in sentence_rates) / len(sentence_rates), 4) if sentence_rates else 0.0,
            "p95_rate": round(percentile([r for _, r in sentence_rates], 95), 4),
            "max_rate": round(max((r for _, r in sentence_rates), default=0.0), 4),
            "sentences_with_fingerspelling": spelled_sentences,
            "sentences_fully_lexical": overall.sentences - spelled_sentences,
            "worst_sentences": [{"id": i, "rate": round(r, 4)}
                                for i, r in sorted(sentence_rates, key=lambda x: -x[1])[:5] if r > 0],
        },
        "match_method_counts": dict(sorted(method_counts.items(), key=lambda kv: -kv[1])),
        "match_method_share": {m: ratio(c, total_tokens) for m, c in
                               sorted(method_counts.items(), key=lambda kv: -kv[1])},
        "avg_confidence_by_method": {m: round(s / n, 4) for m, (s, n) in sorted(method_conf.items()) if n},
        "avg_confidence": round(overall.conf_sum / overall.conf_n, 4) if overall.conf_n else 0.0,
        "gold_entries": gold.gold_entries,
        "gold_lemmas_expected": gold.recall_total,
        "gold_lemma_recall": ratio(gold.recall_hit, gold.recall_total),
        "gold_missed_lemmas": dict(missed.most_common(40)),
        "gold_content_signs": gold.content_signs,
        "gold_lemma_precision": ratio(gold.content_expected, gold.content_signs),
        "gold_unexpected_signs": dict(unexpected.most_common(40)),
        "gold_order_entries": gold.order_entries,
        "gold_order_accuracy": ratio(gold.order_ok, gold.order_entries),
        "gold_order_pairwise_accuracy": ratio(gold.pairs_ok, gold.pairs_total),
        "gold_order_failures": order_failures,
        "by_tag": {tag: by_tag[tag].as_dict() for tag in sorted(by_tag)},
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "max": round(max(latencies, default=0.0), 3),
        },
    }
    metrics["avg_ms_per_sentence"] = metrics["latency_ms"]["mean"]
    if owns_translator:
        translator.close()
    return metrics


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=os.path.join(ROOT, "tests", "data", "eval_corpus.json"))
    ap.add_argument("--out", default=None, help="write metrics JSON to this path")
    ap.add_argument("--quiet", action="store_true", help="do not print the JSON to stdout")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        corpus = json.load(f)["items"]

    metrics = evaluate(corpus)
    text = json.dumps(metrics, ensure_ascii=False, indent=2)
    if not args.quiet:
        print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
