#!/usr/bin/env python3
"""Report plugin catalogs that launch an older Kinocut than the latest PyPI release.

The Hermes Agent community catalog launches whatever ``uvx kinocut==X`` its
listing pins, so a release reaches catalog users only after a re-pin PR
(``scripts/repin_marketplaces.sh``). This check makes a stale pin visible.

    python scripts/check_catalog_pins.py            # exit 1 when a pin is behind
    python scripts/check_catalog_pins.py --latest 2.0.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/kinocut/json"
CATALOGS = {
    "Hermes Agent catalog": "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/plugin-catalog/kinocut.yaml",
}
REPO_MCP = Path(__file__).resolve().parents[1] / "plugins" / "kinocut" / "mcp.json"
PIN = re.compile(r"kinocut==([0-9][0-9A-Za-z.+-]*)")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "kinocut-catalog-pin-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version.split("+")[0])[:3])


def pins_in(text: str) -> set[str]:
    return set(PIN.findall(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--latest", help="Compare against this version instead of PyPI's latest")
    args = parser.parse_args(argv)
    latest = args.latest or json.loads(_get(PYPI_URL))["info"]["version"]

    sources = {name: _get(url) for name, url in CATALOGS.items()}
    sources["plugins/kinocut/mcp.json"] = REPO_MCP.read_text(encoding="utf-8")

    stale = 0
    for name, text in sources.items():
        pins = pins_in(text)
        if not pins:
            print(f"{name}: no kinocut== pin found")
            stale += 1
            continue
        behind = sorted(p for p in pins if _key(p) < _key(latest))
        if behind:
            print(f"{name}: launches kinocut=={', '.join(behind)}; latest is {latest}")
            stale += 1
        else:
            print(f"{name}: up to date ({', '.join(sorted(pins))})")
    if stale:
        print("Re-pin with: bash scripts/repin_marketplaces.sh")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
