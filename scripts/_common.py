"""Shared helpers for the CLI scripts (path bootstrap + pretty printing)."""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``import afl`` work when scripts are run directly (python scripts/x.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tabulate import tabulate  # noqa: E402


def table(df, **kwargs):
    return tabulate(df, headers="keys", tablefmt="github", showindex=False, **kwargs)
