#!/usr/bin/env python3
"""Quality gate for the metrics JSON written by scripts/evaluate.py.

Usage:
    python scripts/check_metrics.py METRICS.json [--corpus NAME]
        [--min-coverage 0.85] [--min-recall 0.95]
        [--min-precision P] [--max-fingerspelling-rate R]
        [--max-common-fingerspelling-rate R]
        [--min-order-accuracy A] [--max-p95-ms MS]

--min-coverage and --min-recall are always enforced (defaults above), except
that for a corpus with no gold entries the gold_* rows are left out of the
table and the recall gate is skipped (recall is undefined there). The other gates are enforced only when
given. With a multi-corpus file from ``evaluate.py --corpus A --corpus B``,
the top level is the first corpus; ``--corpus NAME`` gates the one stored under
``corpora[NAME]`` instead (name = file name without extension). Prints a compact table of the key metrics
and exits 0 when every enforced threshold passes, 1 when any fails, 2 on
unreadable input or when a requested metric is missing from the file.
"""

import argparse
import json
import sys

# (label, metrics key, nested key or None, format)
REPORT_ROWS = [
    ("lexical_coverage", "lexical_coverage", None, "{:.4f}"),
    ("fingerspelling_rate", "fingerspelling_rate", None, "{:.4f}"),
    ("common_fingerspelling_rate", "common_fingerspelled_word_rate", None, "{:.4f}"),
    ("proper_fingerspelling_rate", "proper_fingerspelled_word_rate", None, "{:.4f}"),
    ("letters_per_lexical_sign", "letters_per_lexical_sign", None, "{:.3f}"),
    ("gold_lemma_recall", "gold_lemma_recall", None, "{:.4f}"),
    ("gold_lemma_precision", "gold_lemma_precision", None, "{:.4f}"),
    ("gold_order_accuracy", "gold_order_accuracy", None, "{:.4f}"),
    ("latency_p50_ms", "latency_ms", "p50", "{:.2f}"),
    ("latency_p95_ms", "latency_ms", "p95", "{:.2f}"),
]


def lookup(metrics, key, sub=None):
    """Return a numeric metric or None when absent."""
    value = metrics.get(key)
    if sub is not None:
        value = value.get(sub) if isinstance(value, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("metrics", help="metrics JSON from scripts/evaluate.py")
    ap.add_argument("--corpus", default=None,
                    help="gate corpora[NAME] of a multi-corpus metrics file instead of the top level")
    ap.add_argument("--min-coverage", type=float, default=0.85, help="minimum lexical_coverage")
    ap.add_argument("--min-recall", type=float, default=0.95, help="minimum gold_lemma_recall")
    ap.add_argument("--min-precision", type=float, default=None,
                    help="minimum gold_lemma_precision (extra unexpected content signs lower it)")
    ap.add_argument("--max-fingerspelling-rate", type=float, default=None,
                    help="maximum share of output tokens that are fingerspelled")
    ap.add_argument("--max-common-fingerspelling-rate", type=float, default=None,
                    help="maximum share of COMMON (non proper-noun) words that are fingerspelled")
    ap.add_argument("--min-order-accuracy", type=float, default=None,
                    help="minimum gold_order_accuracy (TIME first / NEGATION last entries)")
    ap.add_argument("--max-p95-ms", type=float, default=None,
                    help="maximum p95 latency per sentence in milliseconds")
    args = ap.parse_args(argv)

    try:
        with open(args.metrics, encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict):
            raise ValueError("top-level JSON value is not an object")
        if args.corpus is not None:
            corpora = m.get("corpora")
            if not isinstance(corpora, dict) or not isinstance(corpora.get(args.corpus), dict):
                raise KeyError(f"corpus {args.corpus!r} (not present in the metrics file)")
            m = corpora[args.corpus]
        # Recall is undefined when the corpus has no gold lemmas: skip that gate.
        recall_gate = None if m.get("gold_lemmas_expected") == 0 else args.min_recall
        gates = {  # label -> (minimum or None, maximum or None)
            "lexical_coverage": (args.min_coverage, None),
            "gold_lemma_recall": (recall_gate, None),
            "gold_lemma_precision": (args.min_precision, None),
            "fingerspelling_rate": (None, args.max_fingerspelling_rate),
            "common_fingerspelling_rate": (None, args.max_common_fingerspelling_rate),
            "gold_order_accuracy": (args.min_order_accuracy, None),
            "latency_p95_ms": (None, args.max_p95_ms),
        }
        rows = []
        for label, key, sub, fmt in REPORT_ROWS:
            value = lookup(m, key, sub)
            low, high = gates.get(label, (None, None))
            if key.startswith("gold_") and m.get("gold_entries") == 0 and low is None and high is None:
                value = None  # nothing was measured: do not print a misleading 0.0000
            if (low is not None or high is not None) and value is None:
                raise KeyError(f"{label} (not present in the metrics file)")
            rows.append((label, value, fmt, low, high))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: cannot read metrics: {exc}", file=sys.stderr)
        return 2

    failed = False
    lines = []
    for label, value, fmt, low, high in rows:
        if value is None:
            continue
        status, limit = "info", "-"
        if low is not None:
            status, limit = ("PASS" if value >= low else "FAIL"), f">= {fmt.format(low)}"
        elif high is not None:
            status, limit = ("PASS" if value <= high else "FAIL"), f"<= {fmt.format(high)}"
        failed |= status == "FAIL"
        lines.append((label, fmt.format(value), limit, status))

    width = max(len(r[0]) for r in lines) if lines else 0
    print(f"{'metric':<{width}}  {'value':>9}  {'gate':>10}  status")
    for label, value, limit, status in lines:
        print(f"{label:<{width}}  {value:>9}  {limit:>10}  {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
