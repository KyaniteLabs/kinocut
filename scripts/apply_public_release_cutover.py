#!/usr/bin/env python3
"""Apply the Kinocut public release cutover across package + claims surfaces.

The release is a two-phase ceremony, because PyPI is the gate between them:

``--phase prepare`` (before the tag; PyPI does not have the release yet)
    Moves every *candidate* surface to the new version: ``docs/public_claims.json``
    (``release_candidate_version`` only), ``pyproject.toml``, ``kinocut/__init__.py``,
    ``server.json``, ``npm/``, the ``mcp-video`` shim pin, ``mcpb/`` and the
    golden-pack sample receipt. Nothing that a reader could install today moves.

``--phase post-publish`` (after PyPI/npm serve the release)
    Moves every *published-runtime* surface to the new version: the plugin
    manifests under ``plugins/kinocut/``, ``gemini-extension.json``,
    ``smithery.yaml``, the ``kinocut-video-ci`` action default and
    ``public_claims.json``'s ``published_*`` block, then hands the current
    install pins (docs, skills, ``EXPECTED_PINS``) to ``sweep_install_pins.py``.

Dry-run by default. Does NOT rewrite README prose, site HTML, or CHANGELOG
section bodies — those stay manual per docs/RELEASE_RITUAL.md.

Example:
  python scripts/apply_public_release_cutover.py --phase prepare \\
    --version 2.1.0 --date 2026-11-30 --mcp-tools 208 --cli-commands 178 --dry-run
  python scripts/apply_public_release_cutover.py --phase post-publish \\
    --version 2.1.0 --date 2026-11-30 --mcp-tools 208 --cli-commands 178 \\
    --mcp-video-version 1.6.23 --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPI_TIMEOUT = 20
PHASES = ("prepare", "post-publish")
#: Plugin manifests whose ``version`` and ``kinocut==`` pins follow the published runtime.
PLUGIN_MANIFESTS = (
    "plugins/kinocut/plugin.json",
    "plugins/kinocut/.claude-plugin/plugin.json",
    "plugins/kinocut/.cursor-plugin/plugin.json",
    "plugins/kinocut/.minimax-plugin/plugin.json",
    "plugins/kinocut/kimi.plugin.json",
    "plugins/kinocut/mcp.json",
    "plugins/kinocut/.mcp.json",
    "plugins/kinocut/kinocut.mcp.json",
)
VIDEO_CI_ACTION = ".github/actions/kinocut-video-ci/action.yml"
OPENCODE_PLUGIN = "plugins/kinocut/opencode-plugin"
#: The OpenCode helper is JavaScript, so ``_pin_everywhere``'s Python-specific
#: regexes miss its ``RUNTIME_VERSION`` and the pinned manifest next to it.
OPENCODE_MANIFEST = OPENCODE_PLUGIN + "/opencode.json"
OPENCODE_HELPER = OPENCODE_PLUGIN + "/index.js"
#: The packaging lock pins the published runtime and is only valid once PyPI
#: serves the artifacts, so the cutover reports it rather than guessing hashes.
PACKAGING_LOCK = "packaging/claude-plugin/uv.lock"


def _allow_published_version(version: str, *, require_live: bool) -> bool:
    if not require_live:
        return True
    if live_pypi_has_version(version):
        return True
    print(
        f"FAIL: PyPI has no kinocut {version}; refuse to set published_version. "
        "Pass --no-require-live only for local experiments.",
        file=sys.stderr,
    )
    return False


def live_pypi_has_version(version: str, *, opener=urllib.request.urlopen) -> bool:
    url = f"https://pypi.org/pypi/kinocut/{version}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "kinocut-cutover/2.0"})
    try:
        with opener(req, timeout=PYPI_TIMEOUT) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _replace_file(path: Path, old: str, new: str, *, apply: bool) -> bool:
    if not path.is_file():
        print(f"  SKIP (absent): {path.relative_to(ROOT)}")
        return False
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
    if not path.is_file():
        print(f"  SKIP (absent): {path.relative_to(ROOT)}")
        return False
    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(pattern, repl, text, flags=flags)
    if n == 0:
        print(f"  SKIP (no re match): {path.relative_to(ROOT)} /{pattern}/")
        return False
    print(f"  {'WRITE' if apply else 'WOULD'} {path.relative_to(ROOT)} ({n} re)")
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def _write_json(path: Path, payload: dict, *, apply: bool) -> None:
    print(f"  {'WRITE' if apply else 'WOULD'} {path.relative_to(ROOT)}")
    if apply:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _pin_everywhere(path: Path, old: str, new: str, *, apply: bool) -> int:
    """Replace ``<old>`` wherever it names the Kinocut runtime pin in ``path``."""
    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(rf"(?<=kinocut==){re.escape(old)}(?![0-9A-Za-z.])", new, text)
    if n == 0:
        print(f"  SKIP (no pin): {path.relative_to(ROOT)} kinocut=={old}")
        return 0
    print(f"  {'WRITE' if apply else 'WOULD'} {path.relative_to(ROOT)} ({n} pin)")
    if apply:
        path.write_text(updated, encoding="utf-8")
    return n


def prepare_phase(args: argparse.Namespace, ver: str, prev: str) -> None:
    """Candidate surfaces only: nothing a reader installs today may move."""
    apply = args.apply
    print("== prepare: candidate surfaces")
    claims_path = ROOT / "docs" / "public_claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims["release_candidate_version"] = ver
    if not args.keep_dev_ahead:
        claims["development_mcp_tools"] = args.mcp_tools
        claims["development_cli_commands"] = args.cli_commands
    _write_json(claims_path, claims, apply=apply)

    _sub_file(ROOT / "pyproject.toml", r'(?m)^version = "[^"]+"', f'version = "{ver}"', apply=apply)
    _sub_file(ROOT / "kinocut" / "__init__.py", r'(?m)^__version__ = "[^"]+"', f'__version__ = "{ver}"', apply=apply)

    server_path = ROOT / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["version"] = ver
    for pkg in server.get("packages", []):
        pkg["version"] = ver
    _write_json(server_path, server, apply=apply)

    _sub_file(ROOT / "npm" / "package.json", r'"version":\s*"[^"]+"', f'"version": "{ver}"', apply=apply)
    _replace_file(ROOT / "npm" / "bin" / "kinocut.js", f"kinocut=={prev}", f"kinocut=={ver}", apply=apply)

    shim = ROOT / "compat" / "mcp-video-shim" / "pyproject.toml"
    _replace_file(shim, f"kinocut=={prev}", f"kinocut=={ver}", apply=apply)
    if args.mcp_video_version:
        shim_server = ROOT / "compat" / "mcp-video-shim" / "server.json"
        if shim_server.is_file():
            shim_payload = json.loads(shim_server.read_text(encoding="utf-8"))
            if shim_payload.get("version") != args.mcp_video_version:
                shim_payload["version"] = args.mcp_video_version
                for pkg in shim_payload.get("packages", []):
                    pkg["version"] = args.mcp_video_version
                _write_json(shim_server, shim_payload, apply=apply)
        else:
            print(f"  SKIP (absent): {shim_server.relative_to(ROOT)}")

    mcpb_manifest = ROOT / "mcpb" / "manifest.json"
    _sub_file(mcpb_manifest, r'"version":\s*"[^"]+"', f'"version": "{ver}"', apply=apply)
    _replace_file(mcpb_manifest, f"kinocut=={prev}", f"kinocut=={ver}", apply=apply)
    _replace_file(ROOT / "mcpb" / "README.md", f"kinocut=={prev}", f"kinocut=={ver}", apply=apply)

    _replace_file(
        ROOT / "demo" / "golden-pack" / "sample_video_receipt.json",
        f'"kinocut_published_version": "{prev}"',
        f'"kinocut_published_version": "{ver}"',
        apply=apply,
    )


def post_publish_phase(args: argparse.Namespace, ver: str, prev: str) -> int:
    """Published-runtime surfaces: plugin manifests, launch pins, then the doc sweep."""
    apply = args.apply
    print("== post-publish: published-runtime surfaces")
    if not _allow_published_version(ver, require_live=args.require_live):
        return 1

    claims_path = ROOT / "docs" / "public_claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims["published_version"] = ver
    claims["published_date"] = args.date
    claims["published_mcp_tools"] = args.mcp_tools
    claims["published_cli_commands"] = args.cli_commands
    claims["release_candidate_version"] = ver
    if not args.keep_dev_ahead:
        claims["development_mcp_tools"] = args.mcp_tools
        claims["development_cli_commands"] = args.cli_commands
    _write_json(claims_path, claims, apply=apply)

    for relative in PLUGIN_MANIFESTS:
        path = ROOT / relative
        _sub_file(path, r'"version":\s*"[^"]+"', f'"version": "{ver}"', apply=apply)
        _pin_everywhere(path, prev, ver, apply=apply)

    gemini = ROOT / "gemini-extension.json"
    _sub_file(gemini, r'"version":\s*"[^"]+"', f'"version": "{ver}"', apply=apply)
    _pin_everywhere(gemini, prev, ver, apply=apply)
    smithery = ROOT / "smithery.yaml"
    _pin_everywhere(smithery, prev, ver, apply=apply)

    action = ROOT / VIDEO_CI_ACTION
    _sub_file(action, rf'(?m)^(\s+default: "){re.escape(prev)}("\s*)$', rf"\g<1>{ver}\g<2>", apply=apply)

    # The packaging lock pins the published runtime for the plain Claude plugin.
    _pin_everywhere(ROOT / "packaging" / "claude-plugin" / "pyproject.toml", prev, ver, apply=apply)

    # The OpenCode host reads a JavaScript helper, not a Python entry point, so
    # its runtime constant needs its own substitution or the plugin silently
    # launches the outgoing release.
    _sub_file(
        ROOT / OPENCODE_HELPER,
        r'const RUNTIME_VERSION = "[^"]+"',
        f'const RUNTIME_VERSION = "{ver}"',
        apply=apply,
    )
    if (ROOT / OPENCODE_MANIFEST).is_file():
        _pin_everywhere(ROOT / OPENCODE_MANIFEST, prev, ver, apply=apply)
    else:
        print(f"  SKIP (absent): {OPENCODE_MANIFEST}")

    if not args.mcp_video_version:
        print(
            "FAIL: --mcp-video-version is required for post-publish (the shim release that pins this kinocut).",
            file=sys.stderr,
        )
        return 1
    # Current install pins (docs, skills, EXPECTED_PINS) move through the sweep,
    # which uses the pin-sweep test's own grammar so it rewrites exactly what
    # the test checks. Dated records keep their versions there.
    command = [
        sys.executable,
        str(ROOT / "scripts" / "sweep_install_pins.py"),
        "--kinocut",
        ver,
        "--mcp-video",
        args.mcp_video_version,
    ]
    if apply:
        command.append("--apply")
    print("== post-publish: " + " ".join(command))
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--phase",
        choices=PHASES,
        required=True,
        help="prepare = candidate surfaces; post-publish = published-runtime surfaces",
    )
    p.add_argument("--version", required=True, help="e.g. 2.1.0")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--mcp-tools", type=int, required=True)
    p.add_argument("--cli-commands", type=int, required=True)
    p.add_argument("--previous-version", required=True, help="the outgoing published kinocut release, e.g. 2.0.1")
    p.add_argument("--mcp-video-version", help="the mcp-video shim release that pins --version (post-publish)")
    p.add_argument("--apply", action="store_true", help="Write files (default is dry-run)")
    p.add_argument(
        "--keep-dev-ahead",
        action="store_true",
        help="Leave development_* higher than published (default: equalize at tag)",
    )
    p.add_argument(
        "--require-live",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="post-publish: refuse unless PyPI already has --version (default: on)",
    )
    args = p.parse_args()
    ver, prev = args.version, args.previous_version
    print(
        f"Cutover {args.phase}: {prev} → {ver}  mcp={args.mcp_tools} cli={args.cli_commands} date={args.date}  apply={args.apply}"
    )

    if args.phase == "prepare":
        prepare_phase(args, ver, prev)
        print()
        print("Manual next (prepare):")
        print("  - Rewrite README status / What's in / FAQ for the candidate")
        print("  - Promote CHANGELOG Unreleased → ## " + ver)
        print("  - pytest tests/test_public_claims.py tests/test_public_surface.py -q")
        print("  - Tag v" + ver + " only after human go-ahead")
        if not args.apply:
            print("\nDry-run only. Re-run with --apply to write.")
        return 0

    rc = post_publish_phase(args, ver, prev)
    print()
    print("Manual next (post-publish):")
    print("  - Site: kinocut-site/scripts/bump-published-version.sh")
    print(f"  - cd packaging/claude-plugin && uv lock  (regenerate {PACKAGING_LOCK} against PyPI {ver})")
    print("  - pytest tests/test_public_claims.py tests/test_install_pin_sweep.py tests/test_public_surface.py -q")
    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
