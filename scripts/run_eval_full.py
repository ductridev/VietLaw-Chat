#!/usr/bin/env python3
"""Thin wrapper around the evaluation system.

`scripts/run_eval.py` is deliberately left untouched: it is the frozen MVP
golden-case runner, its semantics are documented in its own docstring, and
other people's muscle memory and CI may depend on it. This script is the
entry point to the full system instead.

    python3 scripts/run_eval_full.py --base-url http://127.0.0.1:8010 --suite mvp --seed 20260713

Every flag is forwarded to `python -m evaluation.cli run`. See
`evaluation/README.md` for the suites and exit codes.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.cli import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    # Default to `run` so the script mirrors run_eval.py's shape.
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    raise SystemExit(main(argv))
