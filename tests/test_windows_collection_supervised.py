"""Contracts for the branch-only supervised Windows collection diagnostic."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).parents[1]
HELPER = ROOT / ".github" / "scripts" / "windows_collection_supervised.py"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-collection-supervised.yml"
TOKEN = "a" * 64
START_FIELDS = {
    "utc": "2026-09-07T00:00:00Z",
    "elapsed": "0.000",
    "pid": 99,
    "python": "3.14.0",
    "platform": "Windows-2022",
    "runner_os": "Windows",
    "image_os": "win22",
    "github_sha": "d" * 40,
}


def _helper():
    spec = importlib.util.spec_from_file_location("windows_collection_supervised", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _events():
    return _helper().EVENTS


def _complete(recorder: Any, *, collected: int = 2) -> None:
    recorder.write("DIAG_START", **START_FIELDS)
    for index in range(collected):
        nodeid = f"tests/test_example.py::test_{index}"
        recorder.write("COLLECT_START", collector="Module", nodeid=nodeid, elapsed="0.100")
        recorder.write("COLLECT_DONE", collector="Module", nodeid=nodeid, outcome="passed", elapsed="0.200")
    recorder.write("DIAG_RESULT", rc=0, collected=collected, elapsed="0.300")


def test_event_recorder_pairs_collectors_and_sanitizes_private_fields(tmp_path: Path) -> None:
    helper = _events()
    path = tmp_path / "events.private.json"
    recorder = helper.EventRecorder(path, TOKEN)
    _complete(recorder)
    private = helper.read_private_state(path, TOKEN)
    public = helper.sanitize_state(private)
    assert private["sequence"] == 6
    assert private["collector_starts"] == 2
    assert private["collector_completions"] == 2
    assert private["active_collectors"] == []
    assert private["result"] == {"return_code": 0, "collected": 2}
    assert len(private["completed_digest"]) == 64
    rendered = json.dumps(public)
    assert TOKEN not in rendered
    assert "private" not in rendered
    assert "99" not in rendered
    assert public["trace_status"] == "not_captured"


def test_event_recorder_serializes_concurrent_heartbeat_and_collector_events(tmp_path: Path) -> None:
    helper = _events()
    recorder = helper.EventRecorder(tmp_path / "events.private.json", TOKEN)
    recorder.write("DIAG_START", **START_FIELDS)

    def heartbeat() -> None:
        for _ in range(20):
            recorder.write("DIAG_HEARTBEAT", elapsed="0.100")

    thread = threading.Thread(target=heartbeat)
    thread.start()
    for index in range(20):
        nodeid = f"tests/test_concurrent.py::test_{index}"
        recorder.write("COLLECT_START", collector="Function", nodeid=nodeid, elapsed="0.200")
        recorder.write("COLLECT_DONE", collector="Function", nodeid=nodeid, outcome="passed", elapsed="0.300")
    thread.join(timeout=2)
    assert not thread.is_alive()
    recorder.write("DIAG_RESULT", rc=0, collected=20, elapsed="0.400")
    state = helper.read_private_state(recorder.path, TOKEN)
    assert state["sequence"] == 62
    assert state["heartbeat_count"] == 20
    assert state["collector_starts"] == state["collector_completions"] == 20


@pytest.mark.parametrize(
    ("events", "classification"),
    [
        (
            [
                ("COLLECT_START", {"collector": "Module", "nodeid": "tests/a.py", "elapsed": "0.1"}),
                ("COLLECT_START", {"collector": "Module", "nodeid": "tests/a.py", "elapsed": "0.2"}),
            ],
            "collector_duplicate",
        ),
        (
            [
                (
                    "COLLECT_DONE",
                    {"collector": "Module", "nodeid": "tests/a.py", "outcome": "passed", "elapsed": "0.1"},
                )
            ],
            "collector_unmatched",
        ),
        (
            [
                ("COLLECT_START", {"collector": "Module", "nodeid": "tests/a.py", "elapsed": "0.1"}),
                (
                    "COLLECT_DONE",
                    {"collector": "Module", "nodeid": "tests/a.py", "outcome": "unknown", "elapsed": "0.2"},
                ),
            ],
            "invalid_outcome",
        ),
    ],
)
def test_invalid_pairing_becomes_immutable_terminal_failure(
    tmp_path: Path, events: list[tuple[str, dict[str, object]]], classification: str
) -> None:
    helper = _events()
    recorder = helper.EventRecorder(tmp_path / "events.private.json", TOKEN)
    recorder.write("DIAG_START", **START_FIELDS)
    for event, fields in events[:-1]:
        recorder.write(event, **fields)
    with pytest.raises(helper.DiagnosticError, match=classification):
        recorder.write(events[-1][0], **events[-1][1])
    terminal_bytes = recorder.path.read_bytes()
    with pytest.raises(helper.DiagnosticError, match="event_state_terminal"):
        recorder.write("DIAG_HEARTBEAT", elapsed="0.3")
    assert recorder.path.read_bytes() == terminal_bytes


def test_capacity_and_field_limits_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _events()
    monkeypatch.setattr(helper, "MAX_COLLECTOR_PAIRS", 1)
    recorder = helper.EventRecorder(tmp_path / "events.private.json", TOKEN)
    recorder.write("DIAG_START", **START_FIELDS)
    recorder.write("COLLECT_START", collector="Module", nodeid="tests/a.py", elapsed="0.1")
    recorder.write("COLLECT_DONE", collector="Module", nodeid="tests/a.py", outcome="passed", elapsed="0.2")
    with pytest.raises(helper.DiagnosticError, match="collector_capacity_exceeded"):
        recorder.write("COLLECT_START", collector="Module", nodeid="tests/b.py", elapsed="0.3")
    other = helper.EventRecorder(tmp_path / "other.private.json", TOKEN)
    other.write("DIAG_START", **START_FIELDS)
    with pytest.raises(helper.DiagnosticError, match="collector_identity_invalid"):
        other.write("COLLECT_START", collector="X" * 65, nodeid="tests/a.py", elapsed="0.1")


def test_reader_rejects_wrong_token_malformed_oversize_and_symlink(tmp_path: Path) -> None:
    helper = _events()
    path = tmp_path / "events.private.json"
    recorder = helper.EventRecorder(path, TOKEN)
    recorder.write("DIAG_START", **START_FIELDS)
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(path, "b" * 64)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(path, TOKEN)
    path.write_bytes(b"x" * (helper.MAX_EVENT_BYTES + 1))
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(path, TOKEN)

    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(link, TOKEN)


def test_reader_rejects_forged_completed_identity(tmp_path: Path) -> None:
    helper = _events()
    path = tmp_path / "events.private.json"
    recorder = helper.EventRecorder(path, TOKEN)
    _complete(recorder, collected=1)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["last_completed"]["id"] = 2
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(path, TOKEN)


def test_stale_prepared_file_and_interrupted_replace_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _events()
    path = tmp_path / "events.private.json"
    prepared = path.with_name(f".{path.name}.prepared")
    prepared.write_text("stale", encoding="utf-8")
    with pytest.raises(helper.DiagnosticError, match="event_state_write_failed"):
        helper.EventRecorder(path, TOKEN)

    prepared.unlink()
    recorder = helper.EventRecorder(path, TOKEN)
    monkeypatch.setattr(helper.Path, "replace", lambda *_args: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(helper.DiagnosticError, match="event_state_write_failed"):
        recorder.write("DIAG_START", **START_FIELDS)
    assert prepared.exists()
    with pytest.raises(helper.DiagnosticError, match="event_state_invalid"):
        helper.read_private_state(path, TOKEN)


@pytest.mark.parametrize("event", ["DIAG_START", "DIAG_HEARTBEAT", "COLLECT_START", "COLLECT_DONE", "DIAG_RESULT"])
def test_event_recorder_rejects_missing_and_extra_fields(tmp_path: Path, event: str) -> None:
    events = _events()
    valid = {
        "DIAG_START": dict(START_FIELDS),
        "DIAG_HEARTBEAT": {"elapsed": "0.100"},
        "COLLECT_START": {"elapsed": "0.100", "collector": "Module", "nodeid": "tests/a.py"},
        "COLLECT_DONE": {
            "elapsed": "0.100",
            "collector": "Module",
            "nodeid": "tests/a.py",
            "outcome": "passed",
        },
        "DIAG_RESULT": {"elapsed": "0.100", "rc": 0, "collected": 1},
    }[event]
    for mutation in ("missing", "extra"):
        recorder = events.EventRecorder(tmp_path / f"{event}-{mutation}.json", TOKEN)
        if event != "DIAG_START":
            recorder.write("DIAG_START", **START_FIELDS)
        fields = dict(valid)
        if mutation == "missing":
            fields.pop(next(iter(fields)))
        else:
            fields["unexpected"] = "value"
        with pytest.raises(events.DiagnosticError, match="invalid_event"):
            recorder.write(event, **fields)


@pytest.mark.parametrize(
    ("event", "fields", "classification"),
    [
        ("DIAG_START", {**START_FIELDS, "pid": True}, "invalid_event"),
        ("DIAG_START", {**START_FIELDS, "github_sha": "not-a-sha"}, "invalid_event"),
        ("DIAG_HEARTBEAT", {"elapsed": "nan"}, "invalid_event"),
        (
            "COLLECT_START",
            {"elapsed": "0.1", "collector": "Module", "nodeid": "/absolute.py"},
            "collector_identity_invalid",
        ),
        (
            "COLLECT_DONE",
            {"elapsed": "0.1", "collector": "Module", "nodeid": "tests/a.py", "outcome": []},
            "invalid_outcome",
        ),
        ("DIAG_RESULT", {"elapsed": "0.1", "rc": False, "collected": 1}, "invalid_event"),
    ],
)
def test_event_recorder_rejects_invalid_field_values(
    tmp_path: Path, event: str, fields: dict[str, object], classification: str
) -> None:
    events = _events()
    recorder = events.EventRecorder(tmp_path / f"{event}.json", TOKEN)
    if event != "DIAG_START":
        recorder.write("DIAG_START", **START_FIELDS)
    if event == "COLLECT_DONE":
        recorder.write("COLLECT_START", elapsed="0.0", collector="Module", nodeid="tests/a.py")
    with pytest.raises(events.DiagnosticError, match=classification):
        recorder.write(event, **fields)


def test_event_recorder_rejects_non_string_event_without_raw_type_error(tmp_path: Path) -> None:
    events = _events()
    recorder = events.EventRecorder(tmp_path / "invalid-event.json", TOKEN)
    with pytest.raises(events.DiagnosticError, match="invalid_event"):
        recorder.write(["DIAG_START"], **START_FIELDS)


def test_wrapper_blob_uses_repository_relative_path_in_real_git_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    monkeypatch.chdir(tmp_path)
    root = Path("wrapper")
    source = root / ".github/scripts/windows_collection_diagnostic.py"
    source.parent.mkdir(parents=True)
    source.write_text("# reviewed wrapper\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10)
    expected = subprocess.run(
        ["git", "hash-object", ".github/scripts/windows_collection_diagnostic.py"],
        cwd=root,
        check=True,
        timeout=10,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert helper._git_blob(root, ".github/scripts/windows_collection_diagnostic.py") == expected


def test_driver_verifies_sibling_event_helper_before_argument_parsing(tmp_path: Path) -> None:
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    copied_driver = scripts / HELPER.name
    copied_events = scripts / "windows_collection_events.py"
    shutil.copyfile(HELPER, copied_driver)
    shutil.copyfile(HELPER.with_name("windows_collection_events.py"), copied_events)
    accepted = subprocess.run(
        [os.fspath(Path(os.sys.executable)), os.fspath(copied_driver), "--help"],
        check=False,
        timeout=10,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0
    copied_events.write_text(copied_events.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    rejected = subprocess.run(
        [os.fspath(Path(os.sys.executable)), os.fspath(copied_driver), "--help"],
        check=False,
        timeout=10,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "event_source_identity_mismatch" in rejected.stderr


def test_collection_child_redirects_before_loading_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    order: list[str] = []

    class Wrapper:
        _write: Any = None

        @staticmethod
        def main() -> int:
            order.append("main")
            return 0

    monkeypatch.setattr(helper, "_activate_owner", lambda _path: order.append("activate"))
    monkeypatch.setattr(helper, "_redirect_standard_streams", lambda: order.append("redirect"))
    monkeypatch.setattr(helper, "_require_hash", lambda *_args: None)
    monkeypatch.setattr(helper, "_load_module", lambda *_args: order.append("load") or Wrapper)
    monkeypatch.setattr(helper.os, "chdir", lambda _path: order.append("chdir"))
    args = argparse.Namespace(
        owner=tmp_path / "owner.py",
        wrapper=tmp_path / "wrapper.py",
        product_root=tmp_path / "product",
        state=tmp_path / "state.json",
        token=TOKEN,
    )

    assert helper.collection_child(args) == 0
    assert order == ["activate", "redirect", "load", "chdir", "main"]


def test_context_requires_push_attempt_and_exact_source_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()
    roots = {name: tmp_path / name for name in ("driver", "product", "supervisor", "wrapper")}
    for root in roots.values():
        root.mkdir()
    driver_helper = roots["driver"] / ".github/scripts/windows_collection_supervised.py"
    driver_helper.parent.mkdir(parents=True)
    driver_helper.write_text("# driver", encoding="utf-8")
    event_helper = roots["driver"] / ".github/scripts/windows_collection_events.py"
    event_helper.write_text("# events", encoding="utf-8")
    monkeypatch.setattr(helper, "__file__", str(driver_helper))
    monkeypatch.setattr(helper.EVENTS, "__file__", str(event_helper))
    identities = {
        roots["driver"]: {"commit": "d" * 40, "tree": "e" * 40},
        roots["product"]: {"commit": helper.PRODUCT_COMMIT, "tree": helper.PRODUCT_TREE},
        roots["supervisor"]: {"commit": helper.SUPERVISOR_COMMIT, "tree": helper.SUPERVISOR_TREE},
        roots["wrapper"]: {"commit": helper.WRAPPER_COMMIT, "tree": helper.WRAPPER_TREE},
    }
    monkeypatch.setattr(helper, "_git_identity", identities.__getitem__)
    monkeypatch.setattr(helper, "_require_hash", lambda *_args: None)
    monkeypatch.setattr(
        helper,
        "_git_blob",
        lambda _root, relative: helper.EVENTS_BLOB if relative.endswith("events.py") else helper.WRAPPER_BLOB,
    )
    monkeypatch.setattr(helper, "_git_head_blob", lambda root, relative: helper._git_blob(root, relative))
    monkeypatch.setenv("GITHUB_SHA", "d" * 40)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF_NAME", helper.EXPECTED_BRANCH)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    args = argparse.Namespace(**{f"{name}_root": root for name, root in roots.items()})

    assert helper._validate_context(args)["product"] == identities[roots["product"]]
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(helper.DiagnosticError, match="driver_identity_mismatch"):
        helper._validate_context(args)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    identities[roots["product"]] = {"commit": helper.PRODUCT_COMMIT, "tree": "f" * 40}
    with pytest.raises(helper.DiagnosticError, match="product_identity_mismatch"):
        helper._validate_context(args)


def test_containment_self_test_requires_timeout_cleanup_and_exact_grandchild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = _helper()

    class BoundedProcessError(RuntimeError):
        classification = "command_timeout"
        cleanup = "passed"

    class Supervisor:
        @staticmethod
        def _run_owned(command: list[str], *, env: dict[str, str], timeout: int) -> None:
            assert command[0] == str(tmp_path / "python314.exe")
            assert timeout == 3
            state = Path(command[command.index("--state") + 1])
            token = command[command.index("--token") + 1]
            helper.EVENTS.atomic_json(
                state,
                {"schema": 1, "token": token, "pid": 4321, "role": "grandchild", "job_membership": "passed"},
                1024,
            )
            raise BoundedProcessError

    Supervisor.BoundedProcessError = BoundedProcessError
    monkeypatch.setattr(helper, "_strict_process_absent", lambda pid: pid == 4321)
    args = argparse.Namespace(
        python314=tmp_path / "python314.exe",
        driver_root=tmp_path / "driver",
    )
    context = {"owner": tmp_path / "owner.py"}
    result = helper._run_self_test(Supervisor, context, args, tmp_path / "work")
    assert result == {
        "status": "passed",
        "exit_class": "command_timeout",
        "cleanup": "passed",
        "job_membership": "passed",
        "grandchild_gone": "passed",
    }


def test_parent_authored_legacy_self_test_marker_is_rejected(tmp_path: Path) -> None:
    helper = _helper()
    state = tmp_path / "state.json"
    helper.EVENTS.atomic_json(state, {"token": TOKEN, "pid": 4321}, 1024)
    with pytest.raises(helper.DiagnosticError, match="self_test_evidence_invalid"):
        helper._read_self_test(state, TOKEN)


def test_self_test_child_waits_for_actual_grandchild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    observed: dict[str, object] = {}

    class Grandchild:
        @staticmethod
        def wait() -> int:
            observed["waited"] = True
            return 7

    def popen(command: list[str], **kwargs: object) -> Grandchild:
        observed.update(command=command, kwargs=kwargs)
        return Grandchild()

    monkeypatch.setattr(helper, "_activate_owner", lambda _path: None)
    monkeypatch.setattr(helper.subprocess, "Popen", popen)
    args = argparse.Namespace(owner=tmp_path / "owner.py", state=tmp_path / "state.json", token=TOKEN)
    assert helper.self_test_child(args) == 7
    command = observed["command"]
    assert isinstance(command, list) and "self-test-grandchild" in command
    assert observed["waited"] is True
    assert not args.state.exists()


def test_grandchild_authors_exact_membership_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    observed: list[str] = []
    monkeypatch.setenv("KINOCUT_MCPB_OWNER_NAME", "exact-job")
    monkeypatch.setattr(helper, "_prove_current_job_membership", observed.append)
    monkeypatch.setattr(helper.os, "getpid", lambda: 4321)
    monkeypatch.setattr(helper.time, "sleep", lambda _seconds: None)
    state = tmp_path / "state.json"
    assert helper.self_test_grandchild(argparse.Namespace(state=state, token=TOKEN)) == 0
    assert observed == ["exact-job"]
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "schema": 1,
        "token": TOKEN,
        "pid": 4321,
        "role": "grandchild",
        "job_membership": "passed",
    }


class _FakeKernel:
    def __init__(
        self, *, member: bool = True, query_ok: bool = True, close_ok: bool = True, job_handle: int = 11
    ) -> None:
        self.member = member
        self.query_ok = query_ok
        self.close_ok = close_ok
        self.job_handle = job_handle
        self.closed: list[int] = []
        self.exit_code = 0
        self.process_handle = 22
        self.job_names: list[str] = []

    def OpenJobObjectW(self, _access: int, _inherit: bool, name: str) -> int:
        self.job_names.append(name)
        return self.job_handle

    def GetCurrentProcess(self) -> int:
        return 33

    def IsProcessInJob(self, _process: int, _job: int, result: object) -> int:
        result._obj.value = int(self.member)  # type: ignore[attr-defined]
        return int(self.query_ok)

    def OpenProcess(self, _access: int, _inherit: bool, _pid: int) -> int:
        return self.process_handle

    def GetExitCodeProcess(self, _handle: int, result: object) -> int:
        result._obj.value = self.exit_code  # type: ignore[attr-defined]
        return int(self.query_ok)

    def CloseHandle(self, handle: int) -> int:
        self.closed.append(handle)
        return int(self.close_ok)


@pytest.mark.parametrize(
    ("member", "query_ok", "close_ok"),
    [(False, True, True), (True, False, True), (True, True, False)],
)
def test_job_membership_false_query_and_close_fail_closed(member: bool, query_ok: bool, close_ok: bool) -> None:
    helper = _helper()
    kernel = _FakeKernel(member=member, query_ok=query_ok, close_ok=close_ok)
    with pytest.raises(helper.DiagnosticError, match="self_test_membership_invalid"):
        helper._prove_current_job_membership("exact-job", kernel=kernel)
    assert kernel.closed == [11]


def test_job_membership_accepts_current_process_in_exact_job() -> None:
    helper = _helper()
    kernel = _FakeKernel()
    helper._prove_current_job_membership("exact-job", kernel=kernel)
    assert kernel.closed == [11]
    assert kernel.job_names == ["exact-job"]


def test_job_open_failure_rejects_without_publishing_or_closing_unknown_handle() -> None:
    helper = _helper()
    kernel = _FakeKernel(job_handle=0)
    with pytest.raises(helper.DiagnosticError, match="self_test_membership_invalid"):
        helper._prove_current_job_membership("exact-job", kernel=kernel)
    assert kernel.closed == []


@pytest.mark.parametrize("failure", ["open_unknown", "query", "alive", "close"])
def test_strict_post_cleanup_query_rejects_uncertainty_and_live_pid(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    helper = _helper()
    kernel = _FakeKernel(query_ok=failure != "query", close_ok=failure != "close")
    if failure == "open_unknown":
        kernel.process_handle = 0
        monkeypatch.setattr(helper.ctypes, "get_last_error", lambda: 5, raising=False)
    if failure == "alive":
        kernel.exit_code = 259
    with pytest.raises(helper.DiagnosticError, match=r"self_test_process_state_unknown|self_test_failed"):
        helper._strict_process_absent(4321, kernel=kernel)
    if kernel.process_handle:
        assert kernel.closed == [kernel.process_handle]


def test_strict_post_cleanup_query_accepts_only_documented_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()
    kernel = _FakeKernel()
    kernel.process_handle = 0
    monkeypatch.setattr(helper.ctypes, "get_last_error", lambda: 87, raising=False)
    assert helper._strict_process_absent(4321, kernel=kernel)


def test_early_self_test_child_exit_cannot_be_classified_as_timeout(tmp_path: Path) -> None:
    helper = _helper()

    class BoundedProcessError(RuntimeError):
        classification = "command_timeout"
        cleanup = "passed"

    class Supervisor:
        @staticmethod
        def _run_owned(_command: list[str], *, env: dict[str, str], timeout: int) -> None:
            assert env and timeout == 3

    Supervisor.BoundedProcessError = BoundedProcessError
    args = argparse.Namespace(python314=tmp_path / "python314.exe", driver_root=tmp_path / "driver")
    with pytest.raises(helper.DiagnosticError, match="self_test_timeout_missing"):
        helper._run_self_test(Supervisor, {"owner": tmp_path / "owner.py"}, args, tmp_path / "work")


def test_success_validation_requires_exact_count_pairing_and_cleanup() -> None:
    helper = _helper()
    collection = {
        "exit_class": "command_passed",
        "cleanup": "passed",
        "actual_tests": helper.EXPECTED_TESTS,
        "return_code": 0,
        "collector_starts": 10,
        "collector_completions": 10,
        "active_collectors": [],
    }
    assert helper.collection_passed(collection)
    for key, bad in (
        ("actual_tests", helper.EXPECTED_TESTS - 1),
        ("cleanup", "failed"),
        ("exit_class", "command_timeout"),
        ("collector_completions", 9),
        ("active_collectors", [{"id": 1}]),
        ("return_code", 1),
    ):
        changed = dict(collection)
        changed[key] = bad
        assert not helper.collection_passed(changed)


def _classifier_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helper = _helper()
    paths = helper._artifact_paths(tmp_path / "driver")
    recorder = helper.EVENTS.EventRecorder(tmp_path / "private.json", TOKEN)
    recorder.write("DIAG_START", **START_FIELDS)
    recorder.write("COLLECT_START", elapsed="0.1", collector="Module", nodeid="tests/a.py")
    recorder.write("COLLECT_DONE", elapsed="0.2", collector="Module", nodeid="tests/a.py", outcome="passed")
    recorder.write("DIAG_RESULT", elapsed="0.3", rc=0, collected=helper.EXPECTED_TESTS)
    public = helper.EVENTS.sanitize_state(helper.EVENTS.read_private_state(recorder.path, TOKEN))
    inventory = {"schema": 1, "packages": [{"name": "kinocut", "version": "1.15.1"}]}
    helper.EVENTS.atomic_json(paths["export"], public, helper.EVENTS.MAX_EVENT_BYTES)
    helper.EVENTS.atomic_json(paths["inventory"], inventory, helper.MAX_INVENTORY_BYTES)
    args = argparse.Namespace(
        **{f"{name}_root": tmp_path / name for name in ("driver", "product", "supervisor", "wrapper")},
        python311=tmp_path / "python311.exe",
        python314=tmp_path / "python314.exe",
        **paths,
    )
    identities = {
        name: {"commit": "d" * 40, "tree": "e" * 40} for name in {"driver", "product", "supervisor", "wrapper"}
    }
    identities["wrapper"].update(blob="b" * 40, sha256="c" * 64)
    fixed = {
        "identities": identities,
        "sources": {
            f"{name}_sha256": "1" * 64 for name in {"driver", "events", "workflow", "supervisor_ci", "supervisor_owner"}
        },
        "python": {
            role: {"version": version, "executable_sha256": "2" * 64}
            for role, version in (("controller", "3.11.9"), ("collection", "3.14.0"))
        },
        "runner": {"os": "Windows", "architecture": "X64", "image": "win22"},
        "dependency_resolution": "range_resolved_not_historical_lock",
    }

    def provenance(_context: dict[str, Any], given: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **fixed,
            "dependency_inventory_sha256": helper._sha256(given.inventory),
            "dependency_count": len(payload["packages"]),
        }

    monkeypatch.setattr(helper, "_validate_context", lambda _args: {"supervisor_ci": tmp_path / "mcpb-ci.py"})
    monkeypatch.setattr(helper, "_require_hash", lambda *_args: None)
    monkeypatch.setattr(helper, "_provenance", provenance)
    collection = {
        "exit_class": "command_passed",
        "cleanup": "passed",
        "elapsed_seconds": 1.25,
        "expected_tests": helper.EXPECTED_TESTS,
        "actual_tests": helper.EXPECTED_TESTS,
        "return_code": 0,
        "collector_starts": public["collector_starts"],
        "collector_completions": public["collector_completions"],
        "active_collectors": public["active_collectors"],
        "completed_digest": public["completed_digest"],
        "last_completed": public["last_completed"],
        "trace_status": "not_captured",
    }
    self_test = {
        "status": "passed",
        "exit_class": "command_timeout",
        "cleanup": "passed",
        "job_membership": "passed",
        "grandchild_gone": "passed",
    }
    receipt = {
        "artifact_kind": "windows_supervised_collection",
        "schema": 1,
        "status": "passed",
        "failure_phase": None,
        "exit_class": "command_passed",
        "trace_status": "not_captured",
        **provenance({}, args, inventory),
        "self_test": self_test,
        "collection": collection,
        "evidence_sha256": helper._sha256(paths["export"]),
    }
    helper.EVENTS.atomic_json(paths["receipt"], receipt, helper.MAX_RECEIPT_BYTES)
    return helper, args, receipt, public, inventory


def test_classifier_requires_complete_receipt_and_accepts_emitted_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper, args, receipt, public, inventory = _classifier_case(tmp_path, monkeypatch)
    assert helper.classify(args) == 0
    assert capsys.readouterr().out == "diagnostic_passed\n"
    truncated = {key: receipt[key] for key in ("status", "trace_status", "sources", "self_test", "collection")}
    helper.EVENTS.atomic_json(args.receipt, truncated, helper.MAX_RECEIPT_BYTES)
    assert helper.classify(args) == 1
    assert capsys.readouterr().out == "diagnostic_failed\n"
    original = receipt
    mutations = [
        lambda r, e, i: r.pop("runner"),
        lambda r, e, i: r.update(extra=True),
        lambda r, e, i: r.update(schema=True),
        lambda r, e, i: r["identities"]["driver"].update(commit="f" * 40),
        lambda r, e, i: r.update(sources=[]),
        lambda r, e, i: r.update(python="forged"),
        lambda r, e, i: r["runner"].update(os="Linux"),
        lambda r, e, i: r.update(dependency_count=True),
        lambda r, e, i: r["self_test"].update(job_membership="failed"),
        lambda r, e, i: r["collection"].update(elapsed_seconds=float("inf")),
        lambda r, e, i: r["collection"].update(actual_tests=helper.EXPECTED_TESTS - 1),
        lambda r, e, i: e.pop("result"),
        lambda r, e, i: e.update(extra=True),
        *(lambda r, e, i, value=value: e.update(sequence=value) for value in (0, 7, "6", True)),
        lambda r, e, i: e.update(schema=True),
        lambda r, e, i: i.update(schema=True),
        lambda r, e, i: i["packages"].append({"name": "pytest", "version": "9"}),
    ]
    for mutate in mutations:
        receipt, export, packages = copy.deepcopy((original, public, inventory))
        mutate(receipt, export, packages)
        helper.EVENTS.atomic_json(args.export, export, helper.EVENTS.MAX_EVENT_BYTES)
        receipt["evidence_sha256"] = helper._sha256(args.export)
        helper.EVENTS.atomic_json(args.receipt, receipt, helper.MAX_RECEIPT_BYTES)
        helper.EVENTS.atomic_json(args.inventory, packages, helper.MAX_INVENTORY_BYTES)
        assert helper.classify(args) == 1
        assert capsys.readouterr().out == "diagnostic_failed\n"


def test_workflow_is_single_attempt_branch_only_and_uploads_only_allowlisted_artifacts() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in workflow
    assert "pull_request:" not in workflow
    assert "branches: [ci/windows-supervised-collection-20260907]" in workflow
    assert "github.run_attempt == 1" in workflow
    assert "runs-on: windows-2022" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "contents: read" in workflow
    assert workflow.count("persist-credentials: false") == 4
    assert "3a940a9e0fb1a5b447ef64cc5ff1b3f8f06cf306" in workflow
    assert "90ad16b33e6449035e9aef02e4563490c3d9c66b" in workflow
    assert "77728c2a369073aaccabd2e04717b61929d19119" in workflow
    first_checkout = workflow.index("uses: actions/checkout@")
    assert workflow.index("git config --global core.autocrlf false") < first_checkout
    assert workflow.index("git config --global core.eol lf") < first_checkout
    assert "core.autocrlf mismatch" in workflow and "core.eol mismatch" in workflow
    assert "windows_collection_events.py" in workflow
    assert _helper().EVENTS_SHA256 in workflow
    assert _helper().EVENTS_BLOB in workflow
    assert workflow.index("event helper SHA-256") < workflow.index("Record bounded dependency inventory")
    assert workflow.count("--driver-root driver --product-root product --supervisor-root supervisor") == 2
    for version in ("3.11", "3.14"):
        save = workflow.split(f"Save Python {version} executable", 1)[1].split("- name:", 1)[0]
        assert "$LASTEXITCODE" in save
        assert save.index("$LASTEXITCODE") < save.index("GITHUB_ENV")
    upload = workflow.split("uses: actions/upload-artifact@", 1)[1]
    assert "evidence/windows-supervised-receipt.json" in upload
    assert "evidence/windows-supervised-events.json" in upload
    assert "evidence/windows-supervised-dependencies.json" in upload
    assert "events.private" not in upload
    assert "trace" not in upload.lower()


def test_driver_declares_full_windows_membership_and_process_query_signatures() -> None:
    source = HELPER.read_text(encoding="utf-8")
    for name in (
        "OpenJobObjectW.argtypes",
        "GetCurrentProcess.argtypes",
        "IsProcessInJob.argtypes",
        "OpenProcess.argtypes",
        "GetExitCodeProcess.argtypes",
        "CloseHandle.argtypes",
    ):
        assert name in source
    assert "wait_pid_gone" not in source and "class EventRecorder" not in source
    assert '"self-test-grandchild"' in source
    assert '"events_sha256": _sha256(context["event_helper"])' in source
