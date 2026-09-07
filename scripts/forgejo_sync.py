#!/usr/bin/env python3
"""Fail-closed GitHub-primary to Forgejo synchronization gates."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

GITHUB_RESPONSE_BYTES = 2 * 1024 * 1024
GITHUB_RUN_OBJECTS = 100
FORGEJO_RESPONSE_BYTES = 64 * 1024 * 1024
FORGEJO_RUN_OBJECTS = 5000
FORGEJO_RUN_RESPONSE_BYTES = 1024 * 1024
HTTP_TIMEOUT_SECONDS = 10
GITHUB_POLL_ATTEMPTS = 90
FORGEJO_DISCOVERY_ATTEMPTS = 20
FORGEJO_RUN_POLL_ATTEMPTS = 240
FORGEJO_RERUN_DISCOVERIES = 5
POLL_INTERVAL_SECONDS = 10
GIT_TIMEOUT_SECONDS = 120
TRIGGER_WORKFLOW_ID = 249485876
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


class SyncError(Exception):
    """A safe synchronization refusal suitable for CI logs."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SyncError("API redirect refused")


def _open_without_redirects(request: urllib.request.Request, *, timeout: float):
    return urllib.request.build_opener(_NoRedirects()).open(request, timeout=timeout)


def _validate_sha(value: object, *, field: str = "commit SHA") -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise SyncError(f"{field} is not a full lowercase SHA-1")
    return value


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/")
    if len(parts) != 2 or any(NAME_PATTERN.fullmatch(part) is None for part in parts):
        raise SyncError("repository must have a safe owner/name form")
    return parts[0], parts[1]


def _api_url(base_url: str, repository: str, suffix: str) -> str:
    owner, name = _repository_parts(repository)
    if not base_url.startswith("https://"):
        raise SyncError("API base URL must use HTTPS")
    return f"{base_url.rstrip('/')}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}{suffix}"


def _read_json_response(response: Any, *, max_bytes: int) -> Any:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise SyncError("API response exceeds the byte limit")
        except ValueError as error:
            raise SyncError("API returned an invalid Content-Length") from error
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise SyncError("API response exceeds the byte limit")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyncError("API response is not valid JSON") from error


def request_json(
    url: str,
    *,
    token: str,
    auth_scheme: str,
    max_bytes: int,
    opener: Callable[..., Any] | None = None,
) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "kinocut-forgejo-sync/1"}
    if token:
        headers["Authorization"] = f"{auth_scheme} {token}"
    request = urllib.request.Request(url, headers=headers)
    open_request = opener or _open_without_redirects
    try:
        with open_request(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return _read_json_response(response, max_bytes=max_bytes)
    except SyncError:
        raise
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        raise SyncError("API request failed") from error


def validate_workflow_event(payload: object, repository: str) -> str:
    if not isinstance(payload, dict):
        raise SyncError("workflow event must be a JSON object")
    event_repo = payload.get("repository")
    run = payload.get("workflow_run")
    if not isinstance(event_repo, dict) or event_repo.get("full_name") != repository:
        raise SyncError("workflow event repository is not the configured source")
    if not isinstance(run, dict):
        raise SyncError("workflow event has no workflow_run object")
    required = {
        "workflow_id": TRIGGER_WORKFLOW_ID,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "head_branch": "master",
        "status": "completed",
        "conclusion": "success",
    }
    if any(run.get(key) != value for key, value in required.items()):
        raise SyncError("workflow event does not identify successful trusted master CI")
    head_repo = run.get("head_repository")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
        raise SyncError("workflow run source repository is not trusted")
    return _validate_sha(run.get("head_sha"), field="workflow head SHA")


def _workflow_spec(value: str) -> tuple[int, str]:
    identifier, separator, path = value.partition(":")
    if not separator or not identifier.isdigit() or not path.startswith(".github/workflows/"):
        raise SyncError("required workflow must be numeric-id:.github/workflows/file.yml")
    if path.count("/") != 2 or not path.endswith((".yml", ".yaml")):
        raise SyncError("required workflow path is not a direct workflow file")
    return int(identifier), path


def _workflow_metadata_is_active(data: object, workflow_id: int, expected_path: str) -> None:
    if not isinstance(data, dict):
        raise SyncError("GitHub workflow metadata is malformed")
    if data.get("id") != workflow_id or data.get("path") != expected_path or data.get("state") != "active":
        raise SyncError(f"required primary workflow {workflow_id} is not active at its fixed path")


def _github_runs(data: object) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise SyncError("GitHub workflow-runs response is malformed")
    raw_runs = data["workflow_runs"]
    if len(raw_runs) > GITHUB_RUN_OBJECTS or any(not isinstance(run, dict) for run in raw_runs):
        raise SyncError("GitHub workflow-runs response exceeds the object limit or is malformed")
    return raw_runs


def _newest_github_run(matching: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    identities: set[tuple[int, int]] = set()
    for run in matching:
        values = (run.get("id"), run.get("run_number"), run.get("run_attempt"))
        if any(type(value) is not int or value <= 0 for value in values):
            raise SyncError("matching GitHub workflow run has malformed execution identity")
        identity = (run["id"], run["run_attempt"])
        if identity in identities:
            raise SyncError("GitHub workflow-runs response repeats an execution attempt")
        identities.add(identity)
    return max(matching, key=lambda run: (run["run_number"], run["run_attempt"], run["id"]), default=None)


def github_run_state(data: object, *, sha: str, repository: str, workflow_id: int, path: str) -> str:
    matching = [
        run
        for run in _github_runs(data)
        if run.get("workflow_id") == workflow_id
        and run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("head_branch") == "master"
        and run.get("path") == path
        and isinstance(run.get("head_repository"), dict)
        and run["head_repository"].get("full_name") == repository
    ]
    newest = _newest_github_run(matching)
    if newest is None or newest.get("status") != "completed":
        return "pending"
    return "success" if newest.get("conclusion") == "success" else "failure"


def _github_master_sha(api_url: str, repository: str, token: str, opener: Callable[..., Any] | None) -> str:
    url = _api_url(api_url, repository, "/git/ref/heads/master")
    data = request_json(url, token=token, auth_scheme="Bearer", max_bytes=GITHUB_RESPONSE_BYTES, opener=opener)
    if not isinstance(data, dict) or not isinstance(data.get("object"), dict):
        raise SyncError("GitHub master-ref response is malformed")
    return _validate_sha(data["object"].get("sha"), field="GitHub master SHA")


def _github_workflow_data(
    api_url: str,
    repository: str,
    workflow_id: int,
    suffix: str,
    token: str,
    opener: Callable[..., Any] | None,
) -> Any:
    url = _api_url(api_url, repository, f"/actions/workflows/{workflow_id}{suffix}")
    return request_json(url, token=token, auth_scheme="Bearer", max_bytes=GITHUB_RESPONSE_BYTES, opener=opener)


def poll_primary_workflows(
    *,
    api_url: str,
    repository: str,
    sha: str,
    required_workflows: Sequence[tuple[int, str]],
    token: str,
    attempts: int = GITHUB_POLL_ATTEMPTS,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    for workflow_id, path in required_workflows:
        metadata = _github_workflow_data(api_url, repository, workflow_id, "", token, opener)
        _workflow_metadata_is_active(metadata, workflow_id, path)
    query = urllib.parse.urlencode({"branch": "master", "event": "push", "head_sha": sha, "per_page": 100})
    pending: list[int] = []
    for attempt in range(attempts):
        states: dict[int, str] = {}
        for workflow_id, path in required_workflows:
            data = _github_workflow_data(api_url, repository, workflow_id, f"/runs?{query}", token, opener)
            states[workflow_id] = github_run_state(
                data, sha=sha, repository=repository, workflow_id=workflow_id, path=path
            )
        failed = [workflow_id for workflow_id, state in states.items() if state == "failure"]
        if failed:
            raise SyncError(f"required primary workflow {failed[0]} failed for the exact commit")
        pending = [workflow_id for workflow_id, state in states.items() if state != "success"]
        if not pending:
            return
        if attempt + 1 < attempts:
            sleeper(POLL_INTERVAL_SECONDS)
    raise SyncError(f"required primary workflows did not succeed for the exact commit: {pending}")


def github_gate(
    *,
    event_path: Path,
    repository: str,
    api_url: str,
    required_workflows: Sequence[tuple[int, str]],
    token: str,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    try:
        payload = json.loads(event_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyncError("workflow event cannot be read as JSON") from error
    sha = validate_workflow_event(payload, repository)
    if _github_master_sha(api_url, repository, token, opener) != sha:
        raise SyncError("workflow commit is not the current GitHub master tip")
    poll_primary_workflows(
        api_url=api_url,
        repository=repository,
        sha=sha,
        required_workflows=required_workflows,
        token=token,
        opener=opener,
        sleeper=sleeper,
    )
    if _github_master_sha(api_url, repository, token, opener) != sha:
        raise SyncError("GitHub master advanced while primary workflows were evaluated")
    return sha


def _clean_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("MIRROR_FORGEJO_TOKEN", None)
    environment.pop("MIRROR_FORGEJO_USERNAME", None)
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_TRACE": "0", "GIT_CURL_VERBOSE": "0"})
    return environment


def _run_git(
    arguments: Sequence[str], *, directory: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=directory,
            env=dict(environment),
            text=True,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as error:
        raise SyncError(f"git {arguments[0]} timed out") from error
    except subprocess.CalledProcessError as error:
        raise SyncError(f"git {arguments[0]} failed") from error


def verify_source_tip(directory: Path, source_sha: str) -> None:
    source_sha = _validate_sha(source_sha, field="source SHA")
    environment = _clean_git_environment()
    head = _run_git(["rev-parse", "HEAD"], directory=directory, environment=environment).stdout.strip()
    if head != source_sha:
        raise SyncError("checked-out HEAD does not equal the validated source SHA")
    _run_git(
        ["fetch", "--no-tags", "origin", "refs/heads/master:refs/remotes/origin/master"],
        directory=directory,
        environment=environment,
    )
    observed = _run_git(
        ["rev-parse", "refs/remotes/origin/master"], directory=directory, environment=environment
    ).stdout.strip()
    if observed != source_sha:
        raise SyncError("validated source SHA is no longer the GitHub master tip")


def _credential_environment(username: str, token: str, askpass: Path) -> dict[str, str]:
    if not username or not token:
        raise SyncError("Forgejo mirror credentials are not configured")
    environment = _clean_git_environment()
    environment.update(
        {"GIT_ASKPASS": str(askpass), "MIRROR_FORGEJO_USERNAME": username, "MIRROR_FORGEJO_TOKEN": token}
    )
    return environment


def _create_askpass(directory: Path) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix="forgejo-askpass-", dir=directory)
    except OSError as error:
        raise SyncError("temporary credential helper cannot be created") from error
    path = Path(raw_path)
    script = """#!/bin/sh
case "$1" in
  *Username*) printf '%s\\n' "$MIRROR_FORGEJO_USERNAME" ;;
  *Password*) printf '%s\\n' "$MIRROR_FORGEJO_TOKEN" ;;
  *) exit 1 ;;
esac
"""
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(script)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except OSError as error:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        raise SyncError("temporary credential helper cannot be written") from error
    return path


def _forgejo_runs(data: object) -> list[dict[str, Any]]:
    raw_runs = data.get("workflow_runs") if isinstance(data, dict) else data
    if not isinstance(raw_runs, list):
        raise SyncError("Forgejo workflow-runs response is malformed")
    if len(raw_runs) > FORGEJO_RUN_OBJECTS or any(not isinstance(run, dict) for run in raw_runs):
        raise SyncError("Forgejo workflow-runs response exceeds the object limit or is malformed")
    return raw_runs


def _matching_forgejo_runs(data: object, *, sha: str) -> list[dict[str, Any]]:
    matching = [
        run
        for run in _forgejo_runs(data)
        if run.get("commit_sha") == sha
        and run.get("workflow_id") == "ci.yml"
        and run.get("event") == "push"
        and run.get("trigger_event") == "push"
        and run.get("prettyref") == "master"
    ]
    if any(type(run.get("id")) is not int or run["id"] <= 0 for run in matching):
        raise SyncError("matching Forgejo workflow run has no valid global id")
    if len({run["id"] for run in matching}) != len(matching):
        raise SyncError("Forgejo workflow-runs response repeats a global id")
    return matching


def _newest_forgejo_state(matching: Sequence[dict[str, Any]]) -> str:
    if not matching:
        return "pending"
    newest = max(matching, key=lambda run: run["id"])
    if newest.get("status") == "success":
        return "success"
    active = {"blocked", "queued", "running", "waiting"}
    if newest.get("status") in active:
        return "pending"
    return "failure"


def forgejo_run_state(data: object, *, sha: str) -> str:
    return _newest_forgejo_state(_matching_forgejo_runs(data, sha=sha))


def _discover_forgejo_run(data: object, *, sha: str) -> tuple[str, int | None]:
    matching = _matching_forgejo_runs(data, sha=sha)
    state = _newest_forgejo_state(matching)
    if not matching:
        return state, None
    newest = max(matching, key=lambda run: run["id"])
    return state, newest["id"]


def _forgejo_run_detail_state(data: object, *, sha: str, run_id: int) -> str:
    if not isinstance(data, dict) or data.get("id") != run_id:
        raise SyncError("Forgejo run detail returned the wrong global id")
    matching = _matching_forgejo_runs([data], sha=sha)
    if len(matching) != 1:
        raise SyncError("Forgejo run identity changed during polling")
    return _newest_forgejo_state(matching)


def poll_forgejo_ci(
    *,
    api_url: str,
    repository: str,
    sha: str,
    token: str,
    discovery_attempts: int = FORGEJO_DISCOVERY_ATTEMPTS,
    run_attempts: int = FORGEJO_RUN_POLL_ATTEMPTS,
    rerun_discoveries: int = FORGEJO_RERUN_DISCOVERIES,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    query = urllib.parse.urlencode(
        {"commit_sha": sha, "workflow_id": "ci.yml", "event": "push", "branch": "master", "limit": 5000}
    )
    list_url = _api_url(api_url, repository, f"/actions/runs?{query}")
    run_id = None
    for attempt in range(discovery_attempts):
        data = request_json(list_url, token=token, auth_scheme="token", max_bytes=FORGEJO_RESPONSE_BYTES, opener=opener)
        state, run_id = _discover_forgejo_run(data, sha=sha)
        if state == "success":
            return
        if state == "failure":
            raise SyncError("Forgejo ci.yml failed for the exact mirrored commit")
        if run_id is not None:
            break
        if attempt + 1 < discovery_attempts:
            sleeper(POLL_INTERVAL_SECONDS)
    if run_id is None:
        raise SyncError("Forgejo ci.yml did not appear for the exact mirrored commit")
    detail_url = _api_url(api_url, repository, f"/actions/runs/{run_id}")
    rediscovery_count = 0
    for attempt in range(run_attempts):
        detail = request_json(
            detail_url,
            token=token,
            auth_scheme="token",
            max_bytes=FORGEJO_RUN_RESPONSE_BYTES,
            opener=opener,
        )
        state = _forgejo_run_detail_state(detail, sha=sha, run_id=run_id)
        if state != "pending":
            if rediscovery_count >= rerun_discoveries:
                raise SyncError("Forgejo ci.yml rerun discovery limit was reached")
            latest = request_json(
                list_url, token=token, auth_scheme="token", max_bytes=FORGEJO_RESPONSE_BYTES, opener=opener
            )
            _, latest_id = _discover_forgejo_run(latest, sha=sha)
            rediscovery_count += 1
            if latest_id is None:
                raise SyncError("Forgejo ci.yml disappeared during final verification")
            if latest_id != run_id:
                run_id = latest_id
                detail_url = _api_url(api_url, repository, f"/actions/runs/{run_id}")
                continue
            if state == "success":
                return
            raise SyncError("Forgejo ci.yml failed for the exact mirrored commit")
        if attempt + 1 < run_attempts:
            sleeper(POLL_INTERVAL_SECONDS)
    raise SyncError("Forgejo ci.yml did not succeed for the exact mirrored commit")


def sync_downstream(
    *,
    directory: Path,
    source_sha: str,
    forgejo_git_url: str,
    forgejo_api_url: str,
    forgejo_repository: str,
    username: str,
    token: str,
) -> None:
    verify_source_tip(directory, source_sha)
    if not forgejo_git_url.startswith("https://"):
        raise SyncError("Forgejo Git URL must use HTTPS")
    clean_environment = _clean_git_environment()
    _run_git(
        ["remote", "add", "forgejo-downstream", forgejo_git_url], directory=directory, environment=clean_environment
    )
    askpass = _create_askpass(directory)
    try:
        credential_environment = _credential_environment(username, token, askpass)
        fetch = [
            "fetch",
            "--no-tags",
            "forgejo-downstream",
            "refs/heads/master:refs/remotes/forgejo-downstream/master",
        ]
        _run_git(fetch, directory=directory, environment=credential_environment)
        downstream_sha = _run_git(
            ["rev-parse", "refs/remotes/forgejo-downstream/master"],
            directory=directory,
            environment=clean_environment,
        ).stdout.strip()
        _run_git(
            ["merge-base", "--is-ancestor", downstream_sha, source_sha],
            directory=directory,
            environment=clean_environment,
        )
        verify_source_tip(directory, source_sha)
        _run_git(
            ["push", "forgejo-downstream", f"{source_sha}:refs/heads/master"],
            directory=directory,
            environment=credential_environment,
        )
        _run_git(fetch, directory=directory, environment=credential_environment)
        observed = _run_git(
            ["rev-parse", "refs/remotes/forgejo-downstream/master"],
            directory=directory,
            environment=clean_environment,
        ).stdout.strip()
        if observed != source_sha:
            raise SyncError("Forgejo master does not equal the pushed source SHA")
    finally:
        try:
            askpass.unlink(missing_ok=True)
        except OSError as error:
            raise SyncError("temporary credential helper cannot be removed") from error
    poll_forgejo_ci(
        api_url=forgejo_api_url,
        repository=forgejo_repository,
        sha=source_sha,
        token=token,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("github-gate")
    gate.add_argument("--event", type=Path, required=True)
    gate.add_argument("--repository", required=True)
    gate.add_argument("--api-url", required=True)
    gate.add_argument("--required-workflow", action="append", required=True)
    source = commands.add_parser("source-tip")
    source.add_argument("--repository-dir", type=Path, required=True)
    source.add_argument("--source-sha", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("--repository-dir", type=Path, required=True)
    sync.add_argument("--source-sha", required=True)
    sync.add_argument("--forgejo-git-url", required=True)
    sync.add_argument("--forgejo-api-url", required=True)
    sync.add_argument("--forgejo-repository", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "github-gate":
            workflows = [_workflow_spec(value) for value in args.required_workflow]
            identifiers = [identifier for identifier, _ in workflows]
            paths = [path for _, path in workflows]
            if len(set(identifiers)) != len(identifiers) or len(set(paths)) != len(paths):
                raise SyncError("required workflows must be unique")
            sha = github_gate(
                event_path=args.event,
                repository=args.repository,
                api_url=args.api_url,
                required_workflows=workflows,
                token=os.environ.get("GITHUB_TOKEN", ""),
            )
            print(f"sha={sha}")
        elif args.command == "source-tip":
            verify_source_tip(args.repository_dir, args.source_sha)
            print("source_tip_verified=true")
        else:
            sync_downstream(
                directory=args.repository_dir,
                source_sha=args.source_sha,
                forgejo_git_url=args.forgejo_git_url,
                forgejo_api_url=args.forgejo_api_url,
                forgejo_repository=args.forgejo_repository,
                username=os.environ.get("MIRROR_FORGEJO_USERNAME", ""),
                token=os.environ.get("MIRROR_FORGEJO_TOKEN", ""),
            )
            print(f"mirrored_sha={args.source_sha}")
    except SyncError as error:
        print(f"sync refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
