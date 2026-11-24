"""CLI parity for the spoken-direction review/apply tools."""

from __future__ import annotations

import json

from .common import output_json
from .home_paths import collapse_home


def handle_direct_command(args, *, use_json: bool) -> bool:
    if args.command != "direct":
        return False
    from ..direct import executor
    from ..operation_results import _error_result
    from ..output_policy import output_operation
    from ..tool_routing import retry_context

    with retry_context("direct", cli=True):
        try:
            result = executor.review(args.input, args.direction, output_path=args.output)
            if args.apply and result.get("success") and not result.get("question"):
                with output_operation(args.overwrite or getattr(args, "allow_existing_output", False)):
                    result = executor.apply(result["plan"], confirm=True)
        except Exception as exc:
            result = _error_result(exc)
    if use_json:
        output_json(result)
    else:
        print(json.dumps(_collapse_home_paths(result), indent=2))
    if not result.get("success"):
        raise SystemExit(1)
    return True


def _collapse_home_paths(value):
    """Hide home paths in human-readable direct output before JSON escaping."""
    if isinstance(value, str):
        return collapse_home(value)
    if isinstance(value, list):
        return [_collapse_home_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_collapse_home_paths(item) for item in value)
    if isinstance(value, dict):
        return {_collapse_home_paths(key): _collapse_home_paths(item) for key, item in value.items()}
    return value
