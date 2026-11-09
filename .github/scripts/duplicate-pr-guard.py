#!/usr/bin/env python3
"""Flag a pull request whose issue or Linear ticket another PR already covers.

GitHub issues and Linear tickets can track the same work, and an agent
started from one does not see a PR opened against the other. This check
reads the PR's title, body and branch, collects the GitHub issues and
Linear keys it names, and lists any other PR that references the same
thing and is still open or merged within the lookback window. For a GitHub
issue, only PRs that claim it with a closing keyword (Closes/Fixes #N) count,
so follow-ups that merely mention the issue stay quiet.

It only reads PR text through the GitHub API; it never checks out or runs
PR code. Usage: duplicate-pr-guard.py OWNER/REPO PR_NUMBER
Prints a Markdown report on stdout (empty when nothing overlaps).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys

LINEAR_KEY = re.compile(r"\b(KLH-\d+)\b", re.IGNORECASE)
ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")
LOOKBACK_DAYS = 14

_REFS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        closedByPullRequestsReferences(includeClosedPrs: true, first: 50) {
          nodes { number title state mergedAt url }
        }
      }
    }
  }
}
"""


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def references(text: str) -> tuple[set[int], set[str]]:
    issues = {int(n) for n in ISSUE_REF.findall(text)}
    keys = {k.upper() for k in LINEAR_KEY.findall(text)}
    return issues, keys


def is_live(pr: dict, cutoff: dt.datetime) -> bool:
    state = (pr.get("state") or "").upper()
    if state == "OPEN":
        return True
    merged = pr.get("mergedAt")
    return state == "MERGED" and bool(merged) and dt.datetime.fromisoformat(merged.replace("Z", "+00:00")) >= cutoff


def prs_for_issue(repo: str, number: int) -> list[dict]:
    owner, name = repo.split("/", 1)
    data = json.loads(
        gh(
            "api", "graphql", "-f", f"query={_REFS_QUERY}",
            "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}",
        )
    )  # fmt: skip
    item = data["data"]["repository"]["issueOrPullRequest"]
    if not item or item["__typename"] != "Issue":
        return []  # a PR reference ("supersedes #12") is not a claim on shared work
    return item["closedByPullRequestsReferences"]["nodes"]


def prs_for_key(repo: str, key: str) -> list[dict]:
    rows = json.loads(
        gh(
            "pr", "list", "--repo", repo, "--state", "all", "--limit", "50",
            "--search", f'"{key}" in:title,body', "--json", "number,title,body,state,mergedAt,url",
        )
    )  # fmt: skip
    # Search tokenizes on the hyphen; keep only exact key matches (KLH-34 must not match KLH-340).
    exact = re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE)
    return [row for row in rows if exact.search(f"{row.get('title') or ''} {row.get('body') or ''}")]


def main(repo: str, number: int) -> str:
    me = json.loads(gh("pr", "view", str(number), "--repo", repo, "--json", "title,body,headRefName"))
    issues, keys = references(" ".join([me.get("title") or "", me.get("body") or "", me.get("headRefName") or ""]))
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=LOOKBACK_DAYS)

    overlaps: dict[int, tuple[dict, set[str]]] = {}
    for issue in sorted(issues):
        for pr in prs_for_issue(repo, issue):
            if pr["number"] != number and is_live(pr, cutoff):
                overlaps.setdefault(pr["number"], (pr, set()))[1].add(f"#{issue}")
    for key in sorted(keys):
        for pr in prs_for_key(repo, key):
            if pr["number"] != number and is_live(pr, cutoff):
                overlaps.setdefault(pr["number"], (pr, set()))[1].add(key)

    if not overlaps:
        return ""
    lines = [
        "**Possible duplicate work.** Another PR already covers what this one references:",
        "",
    ]
    for pr_number in sorted(overlaps):
        pr, via = overlaps[pr_number]
        status = "open" if pr["state"].upper() == "OPEN" else f"merged {pr['mergedAt'][:10]}"
        lines.append(f"- #{pr_number} ({status}), via {', '.join(sorted(via))}: {pr['title']}")
    lines += [
        "",
        "Before continuing, compare the two. Close this PR if the other one already covers it, "
        "and port anything it lacks; ignore this if it is a planned follow-up. A Linear key in the PR body (for example `KLH-123`) lets "
        "Linear mark the ticket In Progress so other agents skip it.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(main(sys.argv[1], int(sys.argv[2])))
