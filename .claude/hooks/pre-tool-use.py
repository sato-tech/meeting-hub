#!/usr/bin/env python3
"""Claude Code tool-use 前のログ出力。"""
from __future__ import annotations

import datetime
import sys


def main() -> int:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] tool-use begin", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
