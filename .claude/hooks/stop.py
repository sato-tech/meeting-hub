#!/usr/bin/env python3
"""Claude Code セッション終了時のサマリ。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    out = Path("output")
    if out.exists():
        entries = sorted(p.name for p in out.iterdir())
        print(f"[stop] output/ entries: {entries}", file=sys.stderr)
    else:
        print("[stop] output/ not present yet", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
