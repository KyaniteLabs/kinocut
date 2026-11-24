"""Lint a composition without executing its scripts."""

import argparse
import json
from pathlib import Path

from . import MusicalGrid, lint_composition_keyframes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="HTML, CSS, JS, or resolved JSON events")
    parser.add_argument("--bpm", type=float, required=True)
    parser.add_argument("--offset", type=float, default=0)
    parser.add_argument("--tolerance-ms", type=float, default=2)
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    source = json.loads(text, parse_float=str) if args.source.suffix == ".json" else text
    report = lint_composition_keyframes(
        source, MusicalGrid(args.bpm, offset_s=args.offset), tolerance_ms=args.tolerance_ms
    )
    print(json.dumps(report))
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
