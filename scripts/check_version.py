#!/usr/bin/env python3
"""Verify that every versioned artifact matches the repo-root VERSION file.

Checks: backend_api/server.py (reads VERSION), browser_extension/manifest.json,
docs/openapi.yaml (info.version) and the top release heading in CHANGELOG.md.
Exits 1 on any mismatch. Standard library only.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def collect():
    """Return (source_version, {label: found_version_or_None})."""
    source = _read("VERSION").strip()
    found = {}

    manifest = json.loads(_read("browser_extension/manifest.json"))
    found["browser_extension/manifest.json"] = manifest.get("version")

    spec = _read("docs/openapi.yaml")
    m = re.search(r"^info:\s*\n(?:[ \t]+.*\n|\s*\n)*?[ \t]+version:\s*[\"']?([^\s\"']+)", spec, re.M)
    found["docs/openapi.yaml"] = m.group(1) if m else None

    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", _read("CHANGELOG.md"), re.M)
    found["CHANGELOG.md (top release)"] = m.group(1) if m else None

    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "backend_api"))
    env_backup = os.environ.get("BIBLIONX_PORT")
    try:
        import importlib
        server = importlib.import_module("server")
        found["backend_api/server.py"] = server.VERSION
    finally:
        if env_backup is None:
            os.environ.pop("BIBLIONX_PORT", None)
    return source, found


def check():
    """Return a list of mismatch messages (empty when everything agrees)."""
    source, found = collect()
    problems = []
    if not SEMVER.match(source):
        problems.append(f"VERSION is not MAJOR.MINOR.PATCH: {source!r}")
    for label, value in found.items():
        if value != source:
            problems.append(f"{label}: {value!r} != VERSION {source!r}")
    return problems


def main():
    problems = check()
    if problems:
        for p in problems:
            print("MISMATCH " + p, file=sys.stderr)
        return 1
    print("Versions consistent: " + _read("VERSION").strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
