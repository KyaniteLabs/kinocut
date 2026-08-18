#!/usr/bin/env python3
"""Monitor GitHub CI status + PR review activity (comments/reviews).

Usage examples:
  ./scripts/github-pr-monitor.py --owner KyaniteLabs --repo kinocut
  ./scripts/github-pr-monitor.py --owner KyaniteLabs --repo kinocut --pr 17

Auth (optional):
  export GITHUB_TOKEN=ghp_xxx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.github.com"


def _request_json(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "kinocut-monitor",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: HTTP {exc.code} for {url}\n{detail}", file=sys.stderr)
        raise


def _repo_url(owner: str, repo: str, path: str) -> str:
    safe_owner = urllib.parse.quote(owner)
    safe_repo = urllib.parse.quote(repo)
    return f"{API_BASE}/repos/{safe_owner}/{safe_repo}{path}"


def fetch_workflow_runs(owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
    data = _request_json(_repo_url(owner, repo, f"/actions/runs?per_page={limit}"))
    return data.get("workflow_runs", [])


def fetch_open_prs(owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
    return _request_json(_repo_url(owner, repo, f"/pulls?state=open&per_page={limit}"))


def fetch_pr_activity(
    owner: str, repo: str, pr_number: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    issue_comments = _request_json(_repo_url(owner, repo, f"/issues/{pr_number}/comments?per_page=100"))
    review_comments = _request_json(_repo_url(owner, repo, f"/pulls/{pr_number}/comments?per_page=100"))
    reviews = _request_json(_repo_url(owner, repo, f"/pulls/{pr_number}/reviews?per_page=100"))
    return issue_comments, review_comments, reviews


def print_ci_summary(runs: list[dict[str, Any]]) -> None:
    print("\n=== CI / Workflow summary ===")
    if not runs:
        print("No workflow runs returned.")
        return

    for run in runs:
        name = run.get("name", "(unknown)")
        branch = run.get("head_branch", "(unknown)")
        event = run.get("event", "(unknown)")
        status = run.get("status", "(unknown)")
        conclusion = run.get("conclusion", "-")
        url = run.get("html_url", "")

        icon = (
            "✅"
            if conclusion == "success"
            else ("❌" if conclusion in {"failure", "cancelled", "timed_out", "action_required"} else "⚠️")
        )
        print(f"{icon} {name} | branch={branch} | event={event} | status={status} | conclusion={conclusion}")
        print(f"   {url}")


def _trim_body(text: str, width: int = 140) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= width else compact[: width - 1] + "…"


def print_pr_summary(owner: str, repo: str, prs: list[dict[str, Any]], explicit_pr: int | None) -> int:
    print("\n=== Open pull requests ===")
    if not prs:
        print("No open pull requests.")
        return 0

    for pr in prs:
        print(f"- PR #{pr['number']}: {pr['title']} ({pr['head']['ref']} -> {pr['base']['ref']})")
        print(f"  {pr['html_url']}")

    target_pr = explicit_pr if explicit_pr is not None else prs[0]["number"]
    issue_comments, review_comments, reviews = fetch_pr_activity(owner, repo, target_pr)

    print(f"\n=== Activity on PR #{target_pr} ===")
    print(f"Issue comments: {len(issue_comments)}")
    print(f"Inline review comments: {len(review_comments)}")
    print(f"Reviews: {len(reviews)}")

    if reviews:
        print("\nRecent reviews:")
        for r in reviews[-5:]:
            state = r.get("state", "UNKNOWN")
            user = r.get("user", {}).get("login", "unknown")
            submitted = r.get("submitted_at", "-")
            body = _trim_body(r.get("body", ""))
            print(f"- {state} by {user} at {submitted}")
            if body:
                print(f"  {body}")

    if review_comments:
        print("\nRecent inline review comments:")
        for c in review_comments[-5:]:
            user = c.get("user", {}).get("login", "unknown")
            path = c.get("path", "(unknown file)")
            line = c.get("line")
            body = _trim_body(c.get("body", ""))
            print(f"- {user} on {path}:{line}")
            print(f"  {body}")

    if issue_comments:
        print("\nRecent issue comments:")
        for c in issue_comments[-5:]:
            user = c.get("user", {}).get("login", "unknown")
            created = c.get("created_at", "-")
            body = _trim_body(c.get("body", ""))
            print(f"- {user} at {created}")
            print(f"  {body}")

    attention = 0
    for r in reviews:
        if r.get("state") == "CHANGES_REQUESTED":
            attention += 1
    attention += len(review_comments)

    print("\n=== Attention summary ===")
    if attention == 0:
        print("✅ No requested changes or inline code comments detected.")
    else:
        print(f"⚠️ {attention} review signals need attention (requested changes + inline comments).")

    return attention


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor CI + review comments for a GitHub repo/PR.")
    parser.add_argument("--owner", required=True, help="GitHub owner/org, e.g. KyaniteLabs")
    parser.add_argument("--repo", required=True, help="GitHub repository name, e.g. kinocut")
    parser.add_argument("--pr", type=int, help="Specific PR number to inspect (default: first open PR)")
    parser.add_argument("--run-limit", type=int, default=5, help="How many recent workflow runs to show")
    parser.add_argument("--pr-limit", type=int, default=20, help="How many open PRs to list")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    runs = fetch_workflow_runs(args.owner, args.repo, args.run_limit)
    print_ci_summary(runs)

    prs = fetch_open_prs(args.owner, args.repo, args.pr_limit)
    attention = print_pr_summary(args.owner, args.repo, prs, args.pr)

    return 0 if attention == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
