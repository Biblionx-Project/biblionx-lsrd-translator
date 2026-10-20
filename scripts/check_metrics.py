#!/usr/bin/env python3
"""Quality gate for the metrics JSON written by scripts/evaluate.py.

Usage:
    python scripts/check_metrics.py METRICS.json [--min-coverage 0.85] [--min-recall 0.95]
        [--min-precision P] [--max-fingerspelling-rate R]
        [--min-order-accuracy A] [--max-p95-ms MS]

--min-coverage and --min-recall are always enforced (defaults above). The other
gates are enforced only when given. Prints a compact table of the key metrics
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
    ap.add_argument("--min-coverage", type=float, default=0.85, help="minimum lexical_coverage")
    ap.add_argument("--min-recall", type=float, default=0.95, help="minimum gold_lemma_recall")
    ap.add_argument("--min-precision", type=float, default=None,
                    help="minimum gold_lemma_precision (extra unexpected content signs lower it)")
    ap.add_argument("--max-fingerspelling-rate", type=float, default=None,
                    help="maximum share of output tokens that are fingerspelled")
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
        gates = {  # label -> (minimum or None, maximum or None)
            "lexical_coverage": (args.min_coverage, None),
            "gold_lemma_recall": (args.min_recall, None),
            "gold_lemma_precision": (args.min_precision, None),
            "fingerspelling_rate": (None, args.max_fingerspelling_rate),
            "gold_order_accuracy": (args.min_order_accuracy, None),
            "latency_p95_ms": (None, args.max_p95_ms),
        }
        rows = []
        for label, key, sub, fmt in REPORT_ROWS:
            value = lookup(m, key, sub)
            low, high = gates.get(label, (None, None))
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
