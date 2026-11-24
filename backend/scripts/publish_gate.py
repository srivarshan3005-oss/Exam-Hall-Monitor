"""Fail-safe gate for GitHub Pages publication after an official VSB scan.

Cached records are not proof that the current official-source scan succeeded.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def publish_decision(cycle: dict[str, Any]) -> tuple[bool, str]:
    discovery = cycle.get("discovery") or {}
    if cycle.get("status") == "failed" or discovery.get("status") != "ok":
        return False, (
            f"Official-source scan was not fully successful "
            f"(cycle={cycle.get('status')!r}, discovery={discovery.get('status')!r}); "
            "keeping the last published website."
        )
    try:
        links_found = int(discovery.get("links_found") or 0)
    except (TypeError, ValueError):
        links_found = 0
    if links_found <= 0:
        return False, "The official sources returned no PDF links; keeping the last published website."
    if cycle.get("ingest_error"):
        return False, "PDF ingestion or index rebuilding failed; keeping the last published website."
    ingest = cycle.get("ingest") or {}
    try:
        failed = int(ingest.get("failed") or 0)
    except (TypeError, ValueError):
        failed = 1
    if failed:
        return False, f"{failed} PDF(s) could not be parsed; keeping the last published website."
    return True, (
        f"Official scan succeeded: {links_found} PDF link(s); "
        "ingestion completed without parse failures."
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/publish_gate.py path/to/last-cycle.json", file=sys.stderr)
        return 2
    try:
        cycle = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if not isinstance(cycle, dict):
            raise ValueError("cycle JSON must be an object")
    except Exception as exc:
        print(f"Cannot validate monitoring result: {exc}", file=sys.stderr)
        return 2

    ready, message = publish_decision(cycle)
    print(message)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"ready={'true' if ready else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
