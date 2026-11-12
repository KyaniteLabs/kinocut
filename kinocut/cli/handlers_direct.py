"""CLI parity for the spoken-direction review/apply tools."""

from __future__ import annotations

import json

from .common import output_json


def handle_direct_command(args, *, use_json: bool) -> bool:
    if args.command != "direct":
        return False
    from ..server_tools_direct import video_direct, video_direct_apply

    result = video_direct(args.input, args.direction, output_path=args.output)
    if args.apply and result.get("success") and not result.get("question"):
        result = video_direct_apply(
            result["plan"], confirm=True, overwrite=args.overwrite or getattr(args, "allow_existing_output", False)
        )
    if use_json:
        output_json(result)
    else:
        print(json.dumps(result, indent=2))
    if not result.get("success"):
        raise SystemExit(1)
    return True
