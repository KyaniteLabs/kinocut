#!/usr/bin/env python3
"""Fail-closed live oracle for docs/public_claims.json published_version.

Merge mode (default): exit 1 iff published_version != live PyPI JSON.
npm and GitHub /releases/latest are printed as annotations (ignore drafts).
Does not compare git tips or tags.

Network errors on the PyPI probe are a red failure, not a skip.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "docs" / "public_claims.json"
USER_AGENT = "kinocut-verify-published-claims/1.0"
TIMEOUT = 20


def _get_json(url: str) -> tuple[int, dict | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8")), ""
            except json.JSONDecodeError as exc:
                return resp.status, None, f"invalid JSON: {exc}"
    except urllib.error.HTTPError as exc:
        return exc.code, None, str(exc)
    except Exception as exc:
        return 0, None, str(exc)


def load_claimed_published(path: Path = CLAIMS) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("published_version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("docs/public_claims.json missing published_version")
    return version.strip()


def pypi_latest(package: str = "kinocut") -> tuple[str | None, str]:
    status, body, err = _get_json(f"https://pypi.org/pypi/{package}/json")
    if status != 200 or not body:
        return None, err or f"HTTP {status}"
    version = (body.get("info") or {}).get("version")
    if not isinstance(version, str):
        return None, "missing info.version"
    return version, ""


def npm_latest(package: str = "kinocut") -> tuple[str | None, str]:
    status, body, err = _get_json(f"https://registry.npmjs.org/{package}/latest")
    if status != 200 or not body:
        return None, err or f"HTTP {status}"
    version = body.get("version")
    if not isinstance(version, str):
        return None, "missing version"
    return version, ""


def github_latest_release(repo: str = "KyaniteLabs/kinocut") -> tuple[str | None, str]:
    status, body, err = _get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    if status != 200 or not body:
        return None, err or f"HTTP {status}"
    tag = body.get("tag_name")
    if not isinstance(tag, str):
        return None, "missing tag_name"
    return tag, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, default=CLAIMS)
    args = parser.parse_args(argv)

    claimed = load_claimed_published(args.claims)
    print(f"claimed_published={claimed}")

    pypi, pypi_err = pypi_latest()
    npm, npm_err = npm_latest()
    gh, gh_err = github_latest_release()
    print(f"pypi={pypi or pypi_err}")
    print(f"npm_annotation={npm or npm_err}")
    print(f"github_latest_release_annotation={gh or gh_err}")

    if pypi is None:
        print(f"FAIL: PyPI probe failed ({pypi_err})", file=sys.stderr)
        return 1
    if pypi != claimed:
        print(f"FAIL: published_version {claimed} != PyPI {pypi}", file=sys.stderr)
        return 1
    print("OK: published_version matches live PyPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
