#!/usr/bin/env python3
"""Decide whether a master push re-tests a tree its pull request already passed.

A squash or rebase merge of an up-to-date pull request produces a master commit
whose tree is byte-identical to the pull request head. That head already passed
the same workflow on its ``pull_request`` run, so running the suite again on
master tests nothing new. This helper prints ``tested=true`` only when all of
these hold, and ``tested=false`` otherwise:

* the pushed commit is the merge commit of a merged pull request into master;
* the pull request head's tree equals the pushed commit's tree;
* the newest ``pull_request`` run of the same workflow file for that head
  completed with conclusion ``success``.

Any API error, missing data or ambiguity prints ``tested=false`` so the caller
runs every check (fail-open to testing, never skip-to-green).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

Fetch = Callable[[str], Any]


def _fetch_with(api_url: str, token: str) -> Fetch:
    if not api_url.startswith("https://"):
        raise ValueError(f"refusing non-HTTPS API URL {api_url!r}")

    def fetch(path: str) -> Any:
        request = urllib.request.Request(  # noqa: S310 - HTTPS enforced above
            api_url.rstrip("/") + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - HTTPS enforced above
            return json.load(response)

    return fetch


def _tree(fetch: Fetch, repository: str, sha: str) -> str | None:
    commit = fetch(f"/repos/{repository}/git/commits/{sha}")
    tree = commit.get("tree") if isinstance(commit, dict) else None
    return tree.get("sha") if isinstance(tree, dict) else None


def _ci_pytest_executed(fetch: Fetch, repository: str, run_id: Any, job_name: str, step_name: str) -> tuple[bool, str]:
    """Verify the matched ci.yml PR run actually executed pytest rather than skipping to green."""
    if not isinstance(run_id, int):
        return False, "matched ci.yml run has no integer id"
    jobs_payload = fetch(f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = jobs_payload.get("jobs", []) if isinstance(jobs_payload, dict) else []
    test_jobs = [job for job in jobs if isinstance(job, dict) and job.get("name") == job_name]
    if not test_jobs:
        return False, f"ci.yml run {run_id} has no {job_name} job"
    job = test_jobs[-1]
    if job.get("status") != "completed" or job.get("conclusion") != "success":
        return False, f"{job_name} job in run {run_id} is {job.get('status')}/{job.get('conclusion')}"
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, f"{job_name} job in run {run_id} reported no step outcomes"
    ran_pytest = any(
        isinstance(step, dict) and step.get("name") == step_name and step.get("conclusion") == "success"
        for step in steps
    )
    if not ran_pytest:
        return False, f"{job_name} job in run {run_id} skipped pytest"
    return True, ""


def decide(
    fetch: Fetch,
    repository: str,
    sha: str,
    workflow: str,
    *,
    job_name: str = "Test (Python 3.14)",
    step_name: str = "Run full suite with coverage",
) -> tuple[bool, str]:
    pulls = fetch(f"/repos/{repository}/commits/{sha}/pulls")
    merged = [
        pull
        for pull in (pulls if isinstance(pulls, list) else [])
        if isinstance(pull, dict)
        and pull.get("merged_at")
        and pull.get("merge_commit_sha") == sha
        and isinstance(pull.get("base"), dict)
        and pull["base"].get("ref") == "master"
    ]
    if len(merged) != 1:
        return False, f"{len(merged)} merged pull requests own {sha}"
    pull = merged[0]
    head = pull.get("head", {}).get("sha") if isinstance(pull.get("head"), dict) else None
    if not isinstance(head, str) or len(head) != 40:
        return False, f"pull request #{pull.get('number')} has no head SHA"

    pushed_tree = _tree(fetch, repository, sha)
    head_tree = _tree(fetch, repository, head)
    if not pushed_tree or pushed_tree != head_tree:
        return False, f"tree of {sha} differs from pull request #{pull.get('number')} head {head}"

    query = urllib.parse.urlencode({"head_sha": head, "event": "pull_request", "per_page": 100})
    data = fetch(f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow)}/runs?{query}")
    runs = [
        run
        for run in (data.get("workflow_runs", []) if isinstance(data, dict) else [])
        if isinstance(run, dict) and run.get("head_sha") == head and run.get("event") == "pull_request"
    ]
    if not runs:
        return False, f"no pull_request run of {workflow} for {head}"
    newest = max(runs, key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0), run.get("id", 0)))
    if newest.get("status") != "completed" or newest.get("conclusion") != "success":
        return (
            False,
            f"newest {workflow} run {newest.get('id')} for {head} is {newest.get('status')}/{newest.get('conclusion')}",
        )
    if workflow == "ci.yml":
        executed, reason = _ci_pytest_executed(fetch, repository, newest.get("id"), job_name, step_name)
        if not executed:
            return False, reason
    return (
        True,
        f"tree of {sha} equals pull request #{pull.get('number')} head {head}, which passed {workflow} in run {newest.get('id')}",
    )


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--workflow", required=True, help="workflow file name, e.g. ci.yml")
    parser.add_argument(
        "--job-name",
        default="Test (Python 3.14)",
        help="ci.yml job whose success proves the suite ran (default: %(default)s)",
    )
    parser.add_argument(
        "--step-name",
        default="Run full suite with coverage",
        help="step inside --job-name that must have succeeded (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    try:
        if fetch is None:
            fetch = _fetch_with(os.environ.get("GITHUB_API_URL", "https://api.github.com"), os.environ["GITHUB_TOKEN"])
        tested, reason = decide(
            fetch, args.repository, args.sha, args.workflow, job_name=args.job_name, step_name=args.step_name
        )
    except Exception as error:  # any failure means "run everything"
        tested, reason = False, f"could not decide ({type(error).__name__}: {error})"
    print(f"{'Skipping' if tested else 'Running'} the {args.workflow} suite: {reason}", file=sys.stderr)
    print(f"tested={'true' if tested else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
