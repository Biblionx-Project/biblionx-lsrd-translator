"""Shared helpers for the test suite (stdlib only)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The suite must never reach an AI provider.
for _var in ("BIBLIONX_LLM_PROVIDER", "BIBLIONX_LLM_MODEL", "BIBLIONX_LLM_MAX_CALLS"):
    os.environ.pop(_var, None)
