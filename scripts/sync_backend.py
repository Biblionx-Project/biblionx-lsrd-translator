#!/usr/bin/env python3
"""Sync the shared translation modules and data into backend_api/.

backend_api/ is a standalone deployable copy of the engine. Run from anywhere:

    python scripts/sync_backend.py [--check]

Copies the Python modules, the data/ folder (never the LLM cache) and the
dictionary database. extracted_images/ is intentionally not copied. With
--check nothing is written; the exit code is 1 if backend_api/ is out of date.
"""

import argparse
import filecmp
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "backend_api")

MODULES = [
    "nlp_engine.py", "translator.py", "morphology.py", "ml_matcher.py",
    "dominican_lexicon.py", "phrases.py", "grammar.py", "llm_fallback.py",
]
DATABASE = "lsrd_dictionary.db"
SKIP_DATA = {".llm_cache.json"}


def plan():
    """Yield (source, destination) pairs for every file to sync."""
    for name in MODULES + [DATABASE]:
        yield os.path.join(ROOT, name), os.path.join(DEST, name)
    data_src = os.path.join(ROOT, "data")
    if os.path.isdir(data_src):
        for name in sorted(os.listdir(data_src)):
            src = os.path.join(data_src, name)
            if name in SKIP_DATA or not os.path.isfile(src):
                continue
            yield src, os.path.join(DEST, "data", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report differences without copying")
    args = ap.parse_args()

    stale = 0
    for src, dst in plan():
        rel = os.path.relpath(dst, ROOT).replace(os.sep, "/")
        if not os.path.isfile(src):
            print(f"missing source: {rel}")
            stale += 1
            continue
        if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
            continue
        stale += 1
        if args.check:
            print(f"out of date: {rel}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"copied: {rel}")
    print("backend_api is up to date" if not stale else
          (f"{stale} file(s) differ" if args.check else f"synced {stale} file(s)"))
    return 1 if (stale and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
