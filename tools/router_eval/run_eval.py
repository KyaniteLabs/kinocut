"""CLI: score the frozen set with rules baselines and the d1-2B treatment arm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import operations_by_name
from .dataset import load_dataset
from .runner import evaluate_set, write_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", required=True, help="Path to the private frozen JSONL set")
    parser.add_argument("--endpoint", help="Base URL of the /v1/systemone endpoint")
    parser.add_argument("--rules-only", action="store_true", help="Run R1/R2 only; never touch an endpoint")
    parser.add_argument("--out", help="Write per-item JSONL here (summary goes beside it)")
    parser.add_argument("--limit", type=int, help="Evaluate only the first N items")
    parser.add_argument("--fake-endpoint", action="store_true", help="Use the in-process deterministic fake")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-item endpoint timeout in seconds")
    parser.add_argument("--model", default="d1-2b", help="Model alias sent in the request body")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rules_only and (args.endpoint or args.fake_endpoint):
        parser.error("--rules-only cannot be combined with --endpoint or --fake-endpoint")
    if args.endpoint and args.fake_endpoint:
        parser.error("--endpoint and --fake-endpoint are mutually exclusive")
    if not args.rules_only and not args.endpoint and not args.fake_endpoint:
        parser.error("pass --rules-only, --endpoint URL, or --fake-endpoint")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")

    operations = operations_by_name()
    items = load_dataset(args.set, operations)
    if args.limit is not None:
        items = items[: args.limit]
    records, summary = evaluate_set(
        items,
        operations,
        endpoint=args.endpoint,
        fake_endpoint=args.fake_endpoint,
        timeout=args.timeout,
        model=args.model,
    )
    if args.out:
        write_records(records, args.out)
        Path(f"{args.out}.summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
