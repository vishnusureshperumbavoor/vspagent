#!/usr/bin/env python3
"""Launcher helper invoked by colab-mcp's BROWSER env var to launch Chrome with selected profile."""

from __future__ import annotations

import sys
from vspagent.colab.profiles import open_url_with_profile


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m vspagent.colab.launcher <url>", file=sys.stderr)
        return 2
    url = sys.argv[1]
    try:
        open_url_with_profile(url)
    except Exception as exc:
        print(f"[vspagent launcher] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
