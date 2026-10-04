"""Reviewer helper: propose dictionary synonyms for out-of-vocabulary (OOV) words.

Input : the metrics JSON written by scripts/evaluate.py (--out), or a plain
        text file with one word per line.
Output: data/synonyms_suggested.json, a review file for humans.

Nothing is ever applied automatically. A reviewer copies approved entries
(approved=true) into data/synonyms_extra.json by hand.

Candidates come from ml_matcher.FuzzyMatcher. If BIBLIONX_LLM_PROVIDER is set,
llm_fallback.LLMFallback picks the best candidate; keys are read from the
environment by that module and never handled here.

Usage:
    python tools/suggest_synonyms.py --input metrics.json
    python tools/suggest_synonyms.py --input oov.txt --top 5 --use-llm
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml_matcher import FuzzyMatcher, normalize  # noqa: E402


def load_words(path):
    """Return a list of (word, count) from evaluate.py JSON or a text file."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        items = data.get("top_fingerspelled") or data.get("oov") or []
        out = []
        for it in items:
            if isinstance(it, dict):
                out.append((it.get("word", ""), int(it.get("count", 1))))
            else:
                out.append((str(it), 1))
        return out
    if isinstance(data, list):
        return [(str(w), 1) for w in data]
    return [(line.strip(), 1) for line in raw.splitlines() if line.strip()]


def known_words(extra_path):
    """Words already curated, so they are not proposed again."""
    try:
        with open(extra_path, encoding="utf-8") as fh:
            return {e["word"] for e in json.load(fh).get("entries", [])}
    except (OSError, ValueError, KeyError):
        return set()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True, help="evaluate.py JSON or text file of words")
    ap.add_argument("--db", default=os.path.join(ROOT, "lsrd_dictionary.db"))
    ap.add_argument("--extra", default=os.path.join(ROOT, "data", "synonyms_extra.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "synonyms_suggested.json"))
    ap.add_argument("--top", type=int, default=3, help="candidates per word")
    ap.add_argument("--min-score", type=float, default=0.6)
    ap.add_argument("--use-llm", action="store_true",
                    help="ask the optional LLM fallback to pick (needs BIBLIONX_LLM_PROVIDER)")
    args = ap.parse_args()

    matcher = FuzzyMatcher.from_db(args.db)
    done = known_words(args.extra)

    llm = None
    if args.use_llm:
        try:
            from llm_fallback import LLMFallback
            llm = LLMFallback.from_env()
            if not llm.enabled:
                print("LLM fallback not enabled (set BIBLIONX_LLM_PROVIDER); fuzzy only.")
                llm = None
        except Exception as exc:  # optional dependency path
            print(f"LLM fallback unavailable: {exc}")

    suggestions = []
    for word, count in load_words(args.input):
        norm = normalize(word)
        if not norm or norm in done or norm in matcher.exact:
            continue
        cands = [c for c in matcher.candidates(norm, k=args.top) if c["score"] >= args.min_score]
        if not cands:
            continue
        entry = {
            "word": norm,
            "count": count,
            "candidates": [{"target_norm": c["norm"], "palabra_id": c["palabra_id"],
                            "score": c["score"]} for c in cands],
            "llm_choice": None,
            "approved": False,
            "source": "suggested",
        }
        if llm:
            try:
                pick = llm.choose(norm, "", [c["norm"] for c in cands])
                entry["llm_choice"] = pick
            except Exception:
                pass
        suggestions.append(entry)

    suggestions.sort(key=lambda s: (-s["count"], -s["candidates"][0]["score"]))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"version": 1,
                   "note": "Review only. Set approved=true and copy the chosen target into "
                           "data/synonyms_extra.json manually. Never auto-applied.",
                   "suggestions": suggestions}, fh, ensure_ascii=False, indent=2)
    print(f"{len(suggestions)} suggestions written to {args.out}")


if __name__ == "__main__":
    main()
