#!/usr/bin/env python3
"""Collect Kinocut usage metrics into docs/status/usage-metrics-latest.json.

Sources: GitHub REST (repo, traffic, contributors, recent PRs), PyPI Stats,
MCP Registry. No product telemetry. Requires network; `gh` optional for traffic.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "status" / "usage-metrics-latest.json"
REPO = "KyaniteLabs/kinocut"


def _http_json(url: str) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kinocut-metrics/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return {"_error": str(e)}


def _gh_json(args: list[str]) -> dict | list | None:
    try:
        r = subprocess.run(
            ["gh", "api", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if r.returncode != 0:
            return {"_error": r.stderr.strip() or r.stdout.strip()}
        return json.loads(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"_error": str(e)}


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    repo = _gh_json([f"repos/{REPO}"]) or {}
    views = _gh_json([f"repos/{REPO}/traffic/views"]) or {}
    clones = _gh_json([f"repos/{REPO}/traffic/clones"]) or {}
    paths = _gh_json([f"repos/{REPO}/traffic/popular/paths"]) or []
    contrib = _gh_json([f"repos/{REPO}/contributors?per_page=20"]) or []
    prs = _gh_json([f"repos/{REPO}/pulls?state=all&per_page=30"]) or []

    kinocut_recent = _http_json("https://pypistats.org/api/packages/kinocut/recent")
    mcp_video_recent = _http_json("https://pypistats.org/api/packages/mcp-video/recent")
    registry = _http_json(
        "https://registry.modelcontextprotocol.io/v0/servers/"
        "io.github.KyaniteLabs%2Fkinocut/versions/latest"
    )

    # External human PRs (heuristic: not bots, not simongonzalezdc)
    bots = {"dependabot[bot]", "github-actions[bot]", "kyanitelabs[bot]", "app/dependabot"}
    maintainer = {"simongonzalezdc", "simon", "claude", "noreply", "Codex-Agent"}
    community_prs = []
    if isinstance(prs, list):
        for pr in prs:
            login = (pr.get("user") or {}).get("login") or ""
            if login in bots or login in maintainer:
                continue
            community_prs.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "user": login,
                    "state": pr.get("state"),
                    "merged_at": pr.get("merged_at"),
                    "html_url": pr.get("html_url"),
                }
            )

    payload = {
        "captured_at": now,
        "repo": REPO,
        "github": {
            "stars": repo.get("stargazers_count") if isinstance(repo, dict) else None,
            "forks": repo.get("forks_count") if isinstance(repo, dict) else None,
            "open_issues": repo.get("open_issues_count") if isinstance(repo, dict) else None,
            "pushed_at": repo.get("pushed_at") if isinstance(repo, dict) else None,
            "views": views if isinstance(views, dict) else {"_error": views},
            "clones": clones if isinstance(clones, dict) else {"_error": clones},
            "popular_paths": paths if isinstance(paths, list) else paths,
            "contributors": [
                {"login": c.get("login"), "contributions": c.get("contributions")}
                for c in (contrib if isinstance(contrib, list) else [])
            ],
            "community_prs": community_prs,
        },
        "pypi": {
            "kinocut_recent": kinocut_recent,
            "mcp_video_recent": mcp_video_recent,
        },
        "registry": registry,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"wrote {OUT}")
    if isinstance(repo, dict) and "stargazers_count" in repo:
        print(f"stars={repo['stargazers_count']} forks={repo['forks_count']}")
    if isinstance(views, dict) and "count" in views:
        print(f"views={views.get('count')} uniques={views.get('uniques')}")
    if isinstance(clones, dict) and "count" in clones:
        print(f"clones={clones.get('count')} uniques={clones.get('uniques')}")
    kr = (kinocut_recent or {}).get("data") if isinstance(kinocut_recent, dict) else None
    if isinstance(kr, dict):
        print(f"pypi kinocut day/week/month={kr.get('last_day')}/{kr.get('last_week')}/{kr.get('last_month')}")
    print(f"community_prs={len(community_prs)}")
    for pr in community_prs[:5]:
        print(f"  #{pr['number']} @{pr['user']}: {pr['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
