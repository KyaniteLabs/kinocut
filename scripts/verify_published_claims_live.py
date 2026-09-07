#!/usr/bin/env python3
"""Fail closed unless all official registries match the published claim."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "docs" / "public_claims.json"
USER_AGENT = "kinocut-verify-published-claims/2.0"
TIMEOUT = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _get_json(url: str) -> tuple[int, dict[str, Any] | None, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return response.status, None, "response exceeded byte limit"
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                return response.status, None, "expected JSON object"
            return response.status, body, ""
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return 0, None, str(exc)


def load_claimed_published(path: Path = CLAIMS) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("published_version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit("docs/public_claims.json missing published_version")
    return version.strip()


def _version(url: str, extract: Callable[[dict[str, Any]], object]) -> tuple[str | None, str]:
    status, body, error = _get_json(url)
    if status != 200 or body is None:
        return None, error or f"HTTP {status}"
    try:
        value = extract(body)
    except (KeyError, TypeError):
        return None, "unexpected response schema"
    if not isinstance(value, str) or not value.strip():
        return None, "missing version"
    return value.removeprefix("v"), ""


def pypi_latest(package: str = "kinocut") -> tuple[str | None, str]:
    return _version(f"https://pypi.org/pypi/{package}/json", lambda body: body["info"]["version"])


def npm_latest(package: str = "kinocut") -> tuple[str | None, str]:
    return _version(f"https://registry.npmjs.org/{package}/latest", lambda body: body["version"])


def github_latest_release(repo: str = "KyaniteLabs/kinocut") -> tuple[str | None, str]:
    return _version(f"https://api.github.com/repos/{repo}/releases/latest", lambda body: body["tag_name"])


def mcp_registry_latest(server: str = "io.github.KyaniteLabs/kinocut") -> tuple[str | None, str]:
    identifier = urllib.parse.quote(server, safe="")
    return _version(
        f"https://registry.modelcontextprotocol.io/v0/servers/{identifier}/versions/latest",
        lambda body: body["server"]["version"],
    )


PROVIDERS = (
    ("pypi", pypi_latest),
    ("npm", npm_latest),
    ("github_release", github_latest_release),
    ("mcp_registry", mcp_registry_latest),
)


def verify_claim(claimed: str) -> list[str]:
    failures: list[str] = []
    for name, probe in PROVIDERS:
        version, error = probe()
        print(f"{name}={version or 'unresolved'}")
        if version is None:
            failures.append(f"{name}: {error or 'unresolved'}")
        elif version != claimed:
            failures.append(f"{name}: expected {claimed}, got {version}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, default=CLAIMS)
    args = parser.parse_args(argv)
    claimed = load_claimed_published(args.claims)
    print(f"claimed_published={claimed}")
    failures = verify_claim(claimed)
    if failures:
        print("FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("OK: all official providers match published_version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
