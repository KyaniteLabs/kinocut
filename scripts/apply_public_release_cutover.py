#!/usr/bin/env python3
"""Apply Kinocut public release cutover across package + claims surfaces.

Dry-run by default. Does NOT rewrite README prose, site HTML, or CHANGELOG
section bodies — those stay manual per docs/RELEASE_1.8_CHECKLIST.md.

Example:
  python scripts/apply_public_release_cutover.py \\
    --version 1.8.0 --date 2026-07-15 --mcp-tools 142 --cli-commands 121 --dry-run
  python scripts/apply_public_release_cutover.py ... --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _replace_file(path: Path, old: str, new: str, *, apply: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        print(f"  SKIP (pattern absent): {path.relative_to(ROOT)}")
        return False
    updated = text.replace(old, new)
    if text == updated:
        return False
    print(f"  {'WRITE' if apply else 'WOULD'} {path.relative_to(ROOT)}")
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def _sub_file(path: Path, pattern: str, repl: str, *, apply: bool, flags: int = 0) -> bool:
    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(pattern, repl, text, flags=flags)
    if n == 0:
        print(f"  SKIP (no re match): {path.relative_to(ROOT)} /{pattern}/")
        return False
    print(f"  {'WRITE' if apply else 'WOULD'} {path.relative_to(ROOT)} ({n} re)")
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", required=True, help="e.g. 1.8.0")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--mcp-tools", type=int, required=True)
    p.add_argument("--cli-commands", type=int, required=True)
    p.add_argument("--previous-version", default="1.7.0")
    p.add_argument("--apply", action="store_true", help="Write files (default is dry-run)")
    p.add_argument(
        "--keep-dev-ahead",
        action="store_true",
        help="Leave development_* higher than published (default: equalize at tag)",
    )
    args = p.parse_args()
    apply = args.apply
    ver = args.version
    prev = args.previous_version
    mcp_n = args.mcp_tools
    cli_n = args.cli_commands
    date = args.date

    print(f"Cutover {prev} → {ver}  mcp={mcp_n} cli={cli_n} date={date}  apply={apply}")

    # --- public_claims.json ---
    claims_path = ROOT / "docs" / "public_claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims["published_version"] = ver
    claims["published_date"] = date
    claims["published_mcp_tools"] = mcp_n
    claims["published_cli_commands"] = cli_n
    if not args.keep_dev_ahead:
        claims["development_mcp_tools"] = mcp_n
        claims["development_cli_commands"] = cli_n
    print(f"  {'WRITE' if apply else 'WOULD'} docs/public_claims.json")
    if apply:
        claims_path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")

    # --- pyproject + package version ---
    _sub_file(
        ROOT / "pyproject.toml",
        r'(?m)^version = "[^"]+"',
        f'version = "{ver}"',
        apply=apply,
    )
    _sub_file(
        ROOT / "kinocut" / "__init__.py",
        r'(?m)^__version__ = "[^"]+"',
        f'__version__ = "{ver}"',
        apply=apply,
    )

    # --- server.json ---
    server_path = ROOT / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["version"] = ver
    for pkg in server.get("packages", []):
        pkg["version"] = ver
    print(f"  {'WRITE' if apply else 'WOULD'} server.json")
    if apply:
        server_path.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")

    # --- npm ---
    _sub_file(
        ROOT / "npm" / "package.json",
        r'"version":\s*"[^"]+"',
        f'"version": "{ver}"',
        apply=apply,
        flags=0,
    )

    # --- mcp-video shim pins (all kinocut==prev → kinocut==ver) ---
    shim = ROOT / "compat" / "mcp-video-shim" / "pyproject.toml"
    _replace_file(shim, f"kinocut=={prev}", f"kinocut=={ver}", apply=apply)

    # --- mcpb ---
    mcpb_manifest = ROOT / "mcpb" / "manifest.json"
    _sub_file(
        mcpb_manifest,
        r'"version":\s*"[^"]+"',
        f'"version": "{ver}"',
        apply=apply,
    )
    _replace_file(
        mcpb_manifest,
        f"kinocut=={prev}",
        f"kinocut=={ver}",
        apply=apply,
    )
    _replace_file(
        ROOT / "mcpb" / "README.md",
        f"kinocut=={prev}",
        f"kinocut=={ver}",
        apply=apply,
    )

    # --- golden pack sample ---
    _replace_file(
        ROOT / "demo" / "golden-pack" / "sample_video_receipt.json",
        f'"kinocut_published_version": "{prev}"',
        f'"kinocut_published_version": "{ver}"',
        apply=apply,
    )

    # --- llms.txt published block (best-effort structured lines) ---
    llms = ROOT / "llms.txt"
    _sub_file(
        llms,
        r"\*\*Latest published release:\*\* [^\n]+",
        f"**Latest published release:** {ver} ({date})",
        apply=apply,
    )
    _sub_file(
        llms,
        r"\*\*Published surface[^\n]*\*\*[^\n]+",
        f"**Published surface ({ver}):** {mcp_n} MCP tools / {cli_n} CLI commands",
        apply=apply,
    )
    # Collapse "development tip higher than published" language if equalized
    if not args.keep_dev_ahead:
        _sub_file(
            llms,
            r"\*\*Development tip[^\n]*\*\*[^\n]+",
            f"**Development tip (master at tag):** {mcp_n} MCP tools / {cli_n} CLI commands — matches published {ver}",
            apply=apply,
        )

    print()
    print("Manual next:")
    print("  - Rewrite README status / What's in / FAQ (remove '1.8 not released')")
    print("  - Promote CHANGELOG Unreleased → ## 1.8.0")
    print("  - pytest tests/test_public_claims.py tests/test_public_surface.py -q")
    print("  - Site: kinocut-site/scripts/bump-published-version.sh")
    print("  - Tag v" + ver + " only after human go-ahead")
    if not apply:
        print("\nDry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
