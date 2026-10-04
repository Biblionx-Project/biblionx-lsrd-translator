#!/usr/bin/env python3
"""Quality gate for the metrics JSON written by scripts/evaluate.py.

Usage:
    python scripts/check_metrics.py METRICS.json [--min-coverage 0.85] [--min-recall 0.95]

Exits 0 when all thresholds pass, 1 when any fails, 2 on unreadable input.
"""

import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("metrics", help="metrics JSON from scripts/evaluate.py")
    ap.add_argument("--min-coverage", type=float, default=0.85, help="minimum lexical_coverage")
    ap.add_argument("--min-recall", type=float, default=0.95, help="minimum gold_lemma_recall")
    args = ap.parse_args()

    try:
        with open(args.metrics, encoding="utf-8") as f:
            m = json.load(f)
        checks = [
            ("lexical_coverage", float(m["lexical_coverage"]), args.min_coverage),
            ("gold_lemma_recall", float(m["gold_lemma_recall"]), args.min_recall),
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: cannot read metrics: {exc}", file=sys.stderr)
        return 2

    failed = False
    for name, value, minimum in checks:
        ok = value >= minimum
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: {value:.4f} (min {minimum:.4f})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
