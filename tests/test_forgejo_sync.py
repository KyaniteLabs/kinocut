"""Hostile offline tests for the GitHub-primary Forgejo synchronization gate."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "forgejo_sync.py"
SPEC = importlib.util.spec_from_file_location("forgejo_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

SHA = "1" * 40
OLD_SHA = "2" * 40
REPOSITORY = "KyaniteLabs/kinocut"
WORKFLOWS = (
    (249485876, ".github/workflows/ci.yml"),
    (310965482, ".github/workflows/mirror-smoke.yml"),
    (262986319, ".github/workflows/integration-smoke.yml"),
)
SYNTHETIC_GITHUB_TOKEN = "test-token"  # noqa: S105 -- inert offline fixture credential
SYNTHETIC_FORGEJO_TOKEN = "super-secret"  # noqa: S105 -- inert offline fixture credential


class FakeResponse:
    def __init__(self, payload: object, *, content_length: str | None = None) -> None:
        self.payload = json.dumps(payload).encode()
        self.headers = {} if content_length is None else {"Content-Length": content_length}
        self.read_limits: list[int] = []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return self.payload[:limit]


def workflow_event(**overrides: object) -> dict[str, Any]:
    run: dict[str, Any] = {
        "workflow_id": 249485876,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "head_branch": "master",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPOSITORY},
    }
    run.update(overrides)
    return {"repository": {"full_name": REPOSITORY}, "workflow_run": run}


def github_run(expected_workflow_id: int, expected_path: str, **overrides: object) -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": 8000,
        "run_number": 100,
        "run_attempt": 1,
        "workflow_id": expected_workflow_id,
        "path": expected_path,
        "head_sha": SHA,
        "event": "push",
        "head_branch": "master",
        "head_repository": {"full_name": REPOSITORY},
        "status": "completed",
        "conclusion": "success",
    }
    run.update(overrides)
    return run


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_id", 999),
        ("name", "PR safety"),
        ("path", ".github/workflows/other.yml"),
        ("event", "pull_request"),
        ("head_branch", "feature"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_sha", "not-a-sha"),
        ("head_repository", {"full_name": "attacker/fork"}),
    ],
)
def test_workflow_event_rejects_untrusted_fields(field: str, value: object) -> None:
    with pytest.raises(sync.SyncError):
        sync.validate_workflow_event(workflow_event(**{field: value}), REPOSITORY)


def test_workflow_event_rejects_a_different_event_repository() -> None:
    payload = workflow_event()
    payload["repository"] = {"full_name": "attacker/fork"}
    with pytest.raises(sync.SyncError):
        sync.validate_workflow_event(payload, REPOSITORY)


def test_github_run_selection_never_uses_latest_success_for_another_sha() -> None:
    workflow_id, path = WORKFLOWS[0]
    data = {"workflow_runs": [github_run(workflow_id, path, head_sha=OLD_SHA)]}
    assert sync.github_run_state(data, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == "pending"


@pytest.mark.parametrize(
    "override",
    [
        {"event": "workflow_dispatch"},
        {"head_branch": "feature"},
        {"path": ".github/workflows/renamed.yml"},
        {"head_repository": {"full_name": "attacker/fork"}},
        {"workflow_id": 999},
    ],
)
def test_github_run_selection_rejects_wrong_identity(override: dict[str, object]) -> None:
    workflow_id, path = WORKFLOWS[0]
    data = {"workflow_runs": [github_run(workflow_id, path, **override)]}
    assert sync.github_run_state(data, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == "pending"


def test_github_run_selection_distinguishes_failure_from_pending_and_success() -> None:
    workflow_id, path = WORKFLOWS[0]
    failed = {"workflow_runs": [github_run(workflow_id, path, conclusion="failure")]}
    pending = {"workflow_runs": [github_run(workflow_id, path, status="in_progress", conclusion=None)]}
    passed = {"workflow_runs": [github_run(workflow_id, path)]}
    assert (
        sync.github_run_state(failed, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == "failure"
    )
    assert (
        sync.github_run_state(pending, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == "pending"
    )
    assert (
        sync.github_run_state(passed, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == "success"
    )


@pytest.mark.parametrize(
    ("newest", "expected"),
    [
        ({"id": 8001, "run_number": 101, "status": "completed", "conclusion": "failure"}, "failure"),
        ({"id": 8001, "run_number": 101, "status": "in_progress", "conclusion": None}, "pending"),
        ({"id": 8000, "run_number": 100, "run_attempt": 2, "status": "completed", "conclusion": "failure"}, "failure"),
    ],
)
def test_github_newest_same_sha_attempt_controls_acceptance(newest: dict[str, object], expected: str) -> None:
    workflow_id, path = WORKFLOWS[0]
    old_green = github_run(workflow_id, path)
    newer_run = github_run(workflow_id, path, **newest)
    data = {"workflow_runs": [old_green, newer_run]}
    assert sync.github_run_state(data, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path) == expected


@pytest.mark.parametrize("field", ["id", "run_number", "run_attempt"])
def test_github_matching_run_rejects_malformed_execution_identity(field: str) -> None:
    workflow_id, path = WORKFLOWS[0]
    malformed = github_run(workflow_id, path, **{field: 0})
    with pytest.raises(sync.SyncError, match="malformed execution identity"):
        sync.github_run_state(
            {"workflow_runs": [malformed]}, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path
        )


def test_github_matching_run_rejects_duplicate_attempt_identity() -> None:
    workflow_id, path = WORKFLOWS[0]
    run = github_run(workflow_id, path)
    with pytest.raises(sync.SyncError, match="repeats an execution attempt"):
        sync.github_run_state(
            {"workflow_runs": [run, run.copy()]}, sha=SHA, repository=REPOSITORY, workflow_id=workflow_id, path=path
        )


def test_required_github_workflow_must_be_active_at_fixed_id_and_path() -> None:
    workflow_id, path = WORKFLOWS[0]
    for metadata in (
        {"id": workflow_id, "path": path, "state": "disabled_manually"},
        {"id": workflow_id + 1, "path": path, "state": "active"},
        {"id": workflow_id, "path": ".github/workflows/other.yml", "state": "active"},
    ):
        with pytest.raises(sync.SyncError):
            sync._workflow_metadata_is_active(metadata, workflow_id, path)


def test_api_response_byte_and_object_caps_fail_closed() -> None:
    response = FakeResponse({}, content_length=str(sync.GITHUB_RESPONSE_BYTES + 1))
    with pytest.raises(sync.SyncError, match="byte limit"):
        sync._read_json_response(response, max_bytes=sync.GITHUB_RESPONSE_BYTES)
    too_many = {"workflow_runs": [{}] * (sync.GITHUB_RUN_OBJECTS + 1)}
    with pytest.raises(sync.SyncError, match="object limit"):
        sync._github_runs(too_many)
    with pytest.raises(sync.SyncError, match="object limit"):
        sync._forgejo_runs([{}] * (sync.FORGEJO_RUN_OBJECTS + 1))

    oversized_without_header = FakeResponse("x" * sync.GITHUB_RESPONSE_BYTES)
    with pytest.raises(sync.SyncError, match="byte limit"):
        sync._read_json_response(oversized_without_header, max_bytes=sync.GITHUB_RESPONSE_BYTES)


def test_github_gate_rechecks_tip_after_all_exact_workflows(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(workflow_event()), encoding="utf-8")
    tip_calls = 0

    def opener(request, *, timeout):
        nonlocal tip_calls
        url = request.full_url
        if url.endswith("/git/ref/heads/master"):
            tip_calls += 1
            return FakeResponse({"object": {"sha": SHA if tip_calls == 1 else OLD_SHA}})
        workflow_id = next(identifier for identifier, _ in WORKFLOWS if f"/{identifier}" in url)
        path = dict(WORKFLOWS)[workflow_id]
        if "/runs?" not in url:
            return FakeResponse({"id": workflow_id, "path": path, "state": "active"})
        return FakeResponse({"workflow_runs": [github_run(workflow_id, path)]})

    with pytest.raises(sync.SyncError, match="advanced"):
        sync.github_gate(
            event_path=event_path,
            repository=REPOSITORY,
            api_url="https://api.github.test",
            required_workflows=WORKFLOWS,
            token=SYNTHETIC_GITHUB_TOKEN,
            opener=opener,
            sleeper=lambda _: None,
        )


def test_primary_poll_refuses_inactive_workflow_before_reading_runs() -> None:
    calls: list[str] = []

    def opener(request, *, timeout):
        calls.append(request.full_url)
        return FakeResponse({"id": WORKFLOWS[0][0], "path": WORKFLOWS[0][1], "state": "disabled_manually"})

    with pytest.raises(sync.SyncError, match="not active"):
        sync.poll_primary_workflows(
            api_url="https://api.github.test",
            repository=REPOSITORY,
            sha=SHA,
            required_workflows=WORKFLOWS[:1],
            token=SYNTHETIC_GITHUB_TOKEN,
            attempts=1,
            opener=opener,
            sleeper=lambda _: None,
        )
    assert len(calls) == 1
    assert "/runs?" not in calls[0]


def test_primary_poll_rechecks_prior_success_and_rejects_newer_failure() -> None:
    run_calls = {workflow_id: 0 for workflow_id, _ in WORKFLOWS}

    def opener(request, *, timeout):
        url = request.full_url
        workflow_id = next(identifier for identifier, _ in WORKFLOWS if f"/{identifier}" in url)
        path = dict(WORKFLOWS)[workflow_id]
        if "/runs?" not in url:
            return FakeResponse({"id": workflow_id, "path": path, "state": "active"})
        run_calls[workflow_id] += 1
        if workflow_id == WORKFLOWS[0][0] and run_calls[workflow_id] == 2:
            newer_failure = github_run(
                workflow_id,
                path,
                id=8001,
                run_number=101,
                status="completed",
                conclusion="failure",
            )
            return FakeResponse({"workflow_runs": [newer_failure, github_run(workflow_id, path)]})
        if workflow_id == WORKFLOWS[1][0] and run_calls[workflow_id] == 1:
            return FakeResponse(
                {"workflow_runs": [github_run(workflow_id, path, status="in_progress", conclusion=None)]}
            )
        return FakeResponse({"workflow_runs": [github_run(workflow_id, path)]})

    with pytest.raises(sync.SyncError, match="failed for the exact commit"):
        sync.poll_primary_workflows(
            api_url="https://api.github.test",
            repository=REPOSITORY,
            sha=SHA,
            required_workflows=WORKFLOWS,
            token=SYNTHETIC_GITHUB_TOKEN,
            attempts=2,
            opener=opener,
            sleeper=lambda _: None,
        )

    assert run_calls == {workflow_id: 2 for workflow_id, _ in WORKFLOWS}


@pytest.mark.parametrize(
    "run",
    [
        {
            "id": 7001,
            "head_sha": SHA,
            "workflow_id": "ci.yml",
            "event": "push",
            "trigger_event": "push",
            "prettyref": "master",
            "status": "success",
        },
        {
            "id": 7002,
            "commit_sha": SHA,
            "workflow_id": ".forgejo/workflows/ci.yml",
            "event": "push",
            "trigger_event": "push",
            "prettyref": "master",
            "status": "success",
        },
        {
            "id": 7003,
            "commit_sha": SHA,
            "workflow_id": "ci.yml",
            "event": "workflow_dispatch",
            "trigger_event": "push",
            "prettyref": "master",
            "status": "success",
        },
        {
            "id": 7004,
            "commit_sha": SHA,
            "workflow_id": "ci.yml",
            "event": "push",
            "trigger_event": "push",
            "prettyref": "feature",
            "status": "success",
        },
        {
            "id": 7005,
            "commit_sha": SHA,
            "workflow_id": "ci.yml",
            "event": "push",
            "trigger_event": "workflow_dispatch",
            "prettyref": "master",
            "status": "success",
        },
        {
            "id": 7006,
            "commit_sha": OLD_SHA,
            "workflow_id": "ci.yml",
            "event": "push",
            "trigger_event": "push",
            "prettyref": "master",
            "status": "success",
        },
    ],
)
def test_forgejo_selection_rejects_lookalike_or_wrong_commit_runs(run: dict[str, object]) -> None:
    assert sync.forgejo_run_state([run], sha=SHA) == "pending"


def test_forgejo_selection_requires_exact_success_and_rejects_exact_failure() -> None:
    base = {
        "id": 7009,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
    }
    assert sync.forgejo_run_state([{**base, "status": "running"}], sha=SHA) == "pending"
    assert sync.forgejo_run_state([{**base, "status": "failure"}], sha=SHA) == "failure"
    assert sync.forgejo_run_state([{**base, "status": "success"}], sha=SHA) == "success"


@pytest.mark.parametrize(("status", "expected"), [("failure", "failure"), ("running", "pending")])
def test_forgejo_newest_same_sha_run_controls_acceptance(status: str, expected: str) -> None:
    base = {
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
    }
    runs = [{**base, "id": 7009, "status": "success"}, {**base, "id": 7010, "status": status}]
    assert sync.forgejo_run_state(runs, sha=SHA) == expected
    assert sync._discover_forgejo_run(runs, sha=SHA) == (expected, 7010)


@pytest.mark.parametrize("run_id", [None, 0, -1, True, "7092"])
def test_forgejo_matching_run_rejects_malformed_global_id(run_id: object) -> None:
    run = {
        "id": run_id,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
        "status": "success",
    }
    with pytest.raises(sync.SyncError, match="valid global id"):
        sync.forgejo_run_state([run], sha=SHA)


def test_forgejo_matching_run_rejects_duplicate_global_id() -> None:
    run = {
        "id": 7092,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
        "status": "success",
    }
    with pytest.raises(sync.SyncError, match="repeats a global id"):
        sync.forgejo_run_state([run, run.copy()], sha=SHA)


def test_forgejo_detail_uses_global_id_not_repository_index() -> None:
    run = {
        "id": 7092,
        "index_in_repo": 1060,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
        "status": "running",
    }
    assert sync._forgejo_run_detail_state(run, sha=SHA, run_id=7092) == "pending"
    with pytest.raises(sync.SyncError, match="global id"):
        sync._forgejo_run_detail_state(run, sha=SHA, run_id=1060)


@pytest.mark.parametrize(
    "override",
    [
        {"commit_sha": OLD_SHA},
        {"workflow_id": ".forgejo/workflows/ci.yml"},
        {"event": "workflow_dispatch"},
        {"trigger_event": "workflow_dispatch"},
        {"prettyref": "feature"},
    ],
)
def test_forgejo_detail_revalidates_identity_on_every_poll(override: dict[str, object]) -> None:
    run = {
        "id": 7092,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
        "status": "running",
        **override,
    }
    with pytest.raises(sync.SyncError, match="identity changed"):
        sync._forgejo_run_detail_state(run, sha=SHA, run_id=7092)


def test_forgejo_poll_discovers_once_then_uses_small_global_id_endpoint() -> None:
    base = {
        "id": 7092,
        "index_in_repo": 1060,
        "commit_sha": SHA,
        "workflow_id": "ci.yml",
        "event": "push",
        "trigger_event": "push",
        "prettyref": "master",
    }
    requests: list[tuple[str, FakeResponse]] = []
    detail_statuses = iter(("running", "success"))

    def opener(request, *, timeout):
        if request.full_url.endswith("/actions/runs/7092"):
            response = FakeResponse({**base, "status": next(detail_statuses)})
        else:
            response = FakeResponse([{**base, "status": "queued" if not requests else "success"}])
        requests.append((request.full_url, response))
        return response

    sync.poll_forgejo_ci(
        api_url="https://forgejo.test/api/v1",
        repository="org/repo",
        sha=SHA,
        token=SYNTHETIC_FORGEJO_TOKEN,
        discovery_attempts=1,
        run_attempts=2,
        opener=opener,
        sleeper=lambda _: None,
    )
    assert "/actions/runs?" in requests[0][0]
    assert [url for url, _ in requests[1:]] == [
        "https://forgejo.test/api/v1/repos/org/repo/actions/runs/7092",
        "https://forgejo.test/api/v1/repos/org/repo/actions/runs/7092",
        requests[0][0],
    ]
    assert requests[0][1].read_limits == [sync.FORGEJO_RESPONSE_BYTES + 1]
    assert all(response.read_limits == [sync.FORGEJO_RUN_RESPONSE_BYTES + 1] for _, response in requests[1:3])
    assert requests[3][1].read_limits == [sync.FORGEJO_RESPONSE_BYTES + 1]


def test_forgejo_poll_does_not_let_old_success_mask_newer_failed_rerun() -> None:
    def run(run_id: int, status: str) -> dict[str, object]:
        return {
            "id": run_id,
            "commit_sha": SHA,
            "workflow_id": "ci.yml",
            "event": "push",
            "trigger_event": "push",
            "prettyref": "master",
            "status": status,
        }

    list_calls = 0

    def opener(request, *, timeout):
        nonlocal list_calls
        if request.full_url.endswith("/actions/runs/7092"):
            return FakeResponse(run(7092, "success"))
        if request.full_url.endswith("/actions/runs/7093"):
            return FakeResponse(run(7093, "failure"))
        list_calls += 1
        if list_calls == 1:
            return FakeResponse([run(7092, "running")])
        return FakeResponse([run(7092, "success"), run(7093, "failure")])

    with pytest.raises(sync.SyncError, match="failed for the exact mirrored commit"):
        sync.poll_forgejo_ci(
            api_url="https://forgejo.test/api/v1",
            repository="org/repo",
            sha=SHA,
            token=SYNTHETIC_FORGEJO_TOKEN,
            discovery_attempts=1,
            run_attempts=2,
            opener=opener,
            sleeper=lambda _: None,
        )
    assert list_calls == 3


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], 0, stdout=stdout, stderr="")


def test_divergent_downstream_stops_before_push_and_never_puts_token_in_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_git(arguments, *, directory, environment):
        args = list(arguments)
        calls.append((args, dict(environment)))
        if args == ["rev-parse", "HEAD"] or args == ["rev-parse", "refs/remotes/origin/master"]:
            return completed(SHA + "\n")
        if args == ["rev-parse", "refs/remotes/forgejo-downstream/master"]:
            return completed(OLD_SHA + "\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            raise sync.SyncError("git merge-base failed")
        return completed()

    monkeypatch.setattr(sync, "_run_git", fake_git)
    with pytest.raises(sync.SyncError, match="merge-base"):
        sync.sync_downstream(
            directory=tmp_path,
            source_sha=SHA,
            forgejo_git_url="https://forgejo.test/org/repo.git",
            forgejo_api_url="https://forgejo.test/api/v1",
            forgejo_repository="org/repo",
            username="mirror-user",
            token=SYNTHETIC_FORGEJO_TOKEN,
        )
    assert all(call[0] != "push" for call, _ in calls)
    assert all(SYNTHETIC_FORGEJO_TOKEN not in argument for call, _ in calls for argument in call)
    origin_fetch = next(env for call, env in calls if call[:3] == ["fetch", "--no-tags", "origin"])
    assert "MIRROR_FORGEJO_TOKEN" not in origin_fetch
    assert list(tmp_path.glob("forgejo-askpass-*")) == []


def test_successful_sync_uses_one_ordinary_push_and_exact_downstream_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    downstream_reads = 0
    polled: list[dict[str, object]] = []

    def fake_git(arguments, *, directory, environment):
        nonlocal downstream_reads
        args = list(arguments)
        calls.append((args, dict(environment)))
        if args == ["rev-parse", "HEAD"] or args == ["rev-parse", "refs/remotes/origin/master"]:
            return completed(SHA + "\n")
        if args == ["rev-parse", "refs/remotes/forgejo-downstream/master"]:
            downstream_reads += 1
            return completed((OLD_SHA if downstream_reads == 1 else SHA) + "\n")
        return completed()

    monkeypatch.setattr(sync, "_run_git", fake_git)
    monkeypatch.setattr(sync, "poll_forgejo_ci", lambda **kwargs: polled.append(kwargs))
    sync.sync_downstream(
        directory=tmp_path,
        source_sha=SHA,
        forgejo_git_url="https://forgejo.test/org/repo.git",
        forgejo_api_url="https://forgejo.test/api/v1",
        forgejo_repository="org/repo",
        username="mirror-user",
        token=SYNTHETIC_FORGEJO_TOKEN,
    )
    pushes = [call for call, _ in calls if call[0] == "push"]
    assert pushes == [["push", "forgejo-downstream", f"{SHA}:refs/heads/master"]]
    assert all("--force" not in call and "--force-with-lease" not in call for call, _ in calls)
    assert polled == [
        {
            "api_url": "https://forgejo.test/api/v1",
            "repository": "org/repo",
            "sha": SHA,
            "token": SYNTHETIC_FORGEJO_TOKEN,
        }
    ]
    assert list(tmp_path.glob("forgejo-askpass-*")) == []


def test_workflow_keeps_secret_out_of_gate_and_pins_primary_workflow_ids() -> None:
    workflow = (ROOT / ".github" / "workflows" / "sync-forgejo.yml").read_text(encoding="utf-8")
    gate, push = workflow.split("\n  push:\n", maxsplit=1)
    activation = "vars.KINOCUT_FORGEJO_SYNC_ACTIVE == 'true'"
    assert "workflow_dispatch" not in workflow
    assert "pull_request" not in workflow
    assert workflow.count(activation) == 2
    assert f"if: {activation} && github.event.workflow_run.conclusion == 'success'" in gate
    assert f"if: {activation} && needs.gate.result == 'success' && needs.gate.outputs.sha != ''" in push
    assert "KINOCUT_FORGEJO_SYNC_ACTIVE != 'false'" not in workflow
    assert "environment:" not in gate
    assert "secrets." not in gate
    assert "actions: read" in gate
    assert "environment: forgejo-mirror" in push
    assert push.count("secrets.MIRROR_FORGEJO_TOKEN") == 1
    assert "permissions:\n      contents: read" in push
    assert "actions: read" not in push
    for workflow_id, path in WORKFLOWS:
        assert f"{workflow_id}:{path}" in workflow
    assert "persist-credentials: false" in workflow


def test_reverse_sync_and_forgejo_renovate_are_removed() -> None:
    assert not (ROOT / ".forgejo" / "workflows" / "sync-github.yml").exists()
    assert not (ROOT / ".forgejo" / "workflows" / "renovate.yml").exists()
