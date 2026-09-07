from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "windows_collection_ci.py"
OWNER = ROOT / ".github" / "scripts" / "mcpb_process_owner.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location("windows_collection_ci", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Owner:
    kind = "test_owner"

    def __init__(self, *, activated: bool = True, active: bool = False, close: bool = True) -> None:
        self.activated = activated
        self.is_active = active
        self.close_result = close
        self.calls: list[str] = []

    def environment(self) -> dict[str, str]:
        self.calls.append("environment")
        return {"KINOCUT_TEST_OWNER": "1"}

    def bind(self, _process) -> None:
        self.calls.append("bind")

    def wait_activated(self, _process) -> bool:
        self.calls.append("wait_activated")
        return self.activated

    def active(self) -> bool:
        self.calls.append("active")
        return self.is_active

    def terminate(self) -> bool:
        self.calls.append("terminate")
        self.is_active = False
        return True

    def close(self) -> bool:
        self.calls.append("close")
        return self.close_result


class _Process:
    def __init__(self, returncode: int = 0, *, timeout: bool = False) -> None:
        self.returncode = returncode
        self.timeout = timeout
        self.calls: list[str] = []

    def poll(self):
        return None if self.timeout else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append(f"wait:{timeout}")
        if self.timeout:
            raise subprocess.TimeoutExpired("collection", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.calls.append("terminate")
        self.timeout = False
        self.returncode = 1

    def kill(self) -> None:
        self.calls.append("kill")
        self.timeout = False
        self.returncode = 1


def _install_supervisor(monkeypatch, module, tmp_path, owner, process, *, receipt=None):
    def make_private(**_kwargs):
        private = tmp_path / "private"
        private.mkdir(parents=True)
        return str(private)

    monkeypatch.setattr(module.tempfile, "mkdtemp", make_private)
    monkeypatch.setattr(module, "_owner_helper", lambda: SimpleNamespace(create_owner=lambda _root: owner))

    def popen(command, **kwargs):
        receipt_path = Path(command[command.index("--receipt") + 1])
        token = command[command.index("--token") + 1]
        if receipt is not None:
            receipt_path.write_text(json.dumps(receipt(token)), encoding="utf-8")
        process.command = command
        process.kwargs = kwargs
        return process

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    return module._run_supervised(ROOT, timeout=120.0)


def test_canonical_owner_is_byte_identical() -> None:
    assert hashlib.sha256(OWNER.read_bytes()).hexdigest() == (
        "e60f20dde7a46edb123033b945f894c4bbf95d407ea52634ed40d6aa7a062681"
    )


def test_workflow_uses_bounded_supervised_collection_and_preserves_later_steps() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    suffix_marker = "      - name: Import checks (server tree imports on Windows)\n"
    collection = workflow.split("      - name: Collect whole test suite\n", 1)[1].split(suffix_marker, 1)[0]
    assert "shell: pwsh" in collection
    assert "timeout-minutes: 4" in collection
    assert "python .github/scripts/windows_collection_ci.py" in collection
    assert "pytest" not in collection
    assert (
        suffix_marker + workflow.split(suffix_marker, 1)[1]
        == """      - name: Import checks (server tree imports on Windows)
        if: needs.changes.outputs.code == 'true'
        run: |
          python -c "import kinocut.server"
          python -c "import kinocut.projectstore._filelock"
          python mcp_video.py --version
      - name: Doctor (primary integration paths)
        if: needs.changes.outputs.code == 'true'
        run: kino doctor
      - name: Public-surface tests (platform skips honored)
        if: needs.changes.outputs.code == 'true'
        run: >-
          python -m pytest tests/test_public_surface.py tests/test_doctor.py
          tests/test_models.py tests/test_errors.py
          tests/test_projectstore_filelock.py
          -q --tb=short
      - name: Windows drive-path FFmpeg render
        if: needs.changes.outputs.code == 'true'
        run: >-
          python -m pytest
          tests/test_ffmpeg_filter_path.py::test_windows_drive_and_backslash_paths_render_with_ffmpeg
          -q --tb=short
"""
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"token": "x" * 64, "collected": 1, "returncode": 0},
        {"token": None, "collected": 1, "returncode": 0},
        {"token": "TOKEN", "collected": True, "returncode": 0},
        {"token": "TOKEN", "collected": 0, "returncode": 0},
        {"token": "TOKEN", "collected": 1, "returncode": True},
        {"token": "TOKEN", "collected": 1, "returncode": 1},
        {"token": "TOKEN", "collected": 1, "returncode": 0, "extra": 1},
    ],
)
def test_receipt_rejects_missing_malformed_empty_or_failed_state(tmp_path, payload) -> None:
    module = _load_driver()
    receipt = tmp_path / "receipt.json"
    if payload is not None:
        normalized = {key: ("a" * 64 if value == "TOKEN" else value) for key, value in payload.items()}
        receipt.write_text(json.dumps(normalized), encoding="utf-8")
    with pytest.raises(module.CollectionFailure):
        module._read_receipt(receipt, "a" * 64)


def test_receipt_rejects_symlink_and_oversize(tmp_path) -> None:
    module = _load_driver()
    target = tmp_path / "target"
    target.write_text(json.dumps({"token": "a" * 64, "collected": 3, "returncode": 0}), encoding="utf-8")
    link = tmp_path / "receipt"
    link.symlink_to(target)
    with pytest.raises(module.CollectionFailure):
        module._read_receipt(link, "a" * 64)
    target.write_bytes(b"x" * (module.RECEIPT_MAX_BYTES + 1))
    with pytest.raises(module.CollectionFailure):
        module._read_receipt(target, "a" * 64)


def test_child_activates_before_importing_pytest_and_writes_closed_receipt(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    events: list[str] = []
    owner = SimpleNamespace(activate_child_from_env=lambda: events.append("activate"))
    monkeypatch.setattr(module, "_owner_helper", lambda: owner)
    real_import = __import__

    class FakePytest:
        @staticmethod
        def main(args, plugins):
            events.append("pytest")
            assert args == ["--collect-only", "-qq", "-s", "--tb=short", "--color=no"]
            plugins[0].pytest_collection_finish(SimpleNamespace(items=[1, 2, 3]))
            return 0

    def fake_import(name, *args, **kwargs):
        if name == "pytest":
            events.append("import_pytest")
            return FakePytest
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    receipt = tmp_path / "receipt.json"
    assert module._run_child(receipt, "a" * 64) == 0
    assert events == ["activate", "import_pytest", "pytest"]
    assert json.loads(receipt.read_text(encoding="utf-8")) == {
        "collected": 3,
        "returncode": 0,
        "token": "a" * 64,
    }


def test_parent_launches_complete_collection_with_devnull_and_owner_environment(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner()
    process = _Process()
    count = _install_supervisor(
        monkeypatch,
        module,
        tmp_path,
        owner,
        process,
        receipt=lambda token: {"token": token, "collected": 5371, "returncode": 0},
    )
    assert count == 5371
    assert process.command[:3] == [sys.executable, str(SCRIPT), "--child"]
    assert process.kwargs["cwd"] == ROOT
    assert process.kwargs["stdin"] is subprocess.DEVNULL
    assert process.kwargs["stdout"] is subprocess.DEVNULL
    assert process.kwargs["stderr"] is subprocess.DEVNULL
    assert process.kwargs["env"]["KINOCUT_TEST_OWNER"] == "1"
    if module.os.name != "nt":
        assert process.kwargs["start_new_session"] is True
    assert owner.calls == ["environment", "bind", "wait_activated", "active", "close"]


def test_activation_failure_terminates_unassigned_root_and_closes_owner(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner(activated=False)
    process = _Process(timeout=True)
    with pytest.raises(module.CollectionFailure, match="owner_not_activated"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, process)
    assert "terminate" in owner.calls
    assert "terminate" in process.calls
    assert "close" in owner.calls


def test_launch_failure_closes_empty_owner(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner()
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **_kwargs: str(private))
    monkeypatch.setattr(module, "_owner_helper", lambda: SimpleNamespace(create_owner=lambda _root: owner))
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("launch")),
    )
    with pytest.raises(module.CollectionFailure, match="owner_not_activated"):
        module._run_supervised(ROOT)
    assert owner.calls == ["environment", "terminate", "active", "close"]


def test_owner_creation_failure_is_typed(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **_kwargs: str(private))
    monkeypatch.setattr(
        module,
        "_owner_helper",
        lambda: SimpleNamespace(create_owner=lambda _root: (_ for _ in ()).throw(OSError("owner"))),
    )
    with pytest.raises(module.CollectionFailure, match="owner_not_activated"):
        module._run_supervised(ROOT)


def test_timeout_terminates_owner_waits_root_and_requires_inactive(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner(active=True)
    process = _Process(timeout=True)
    with pytest.raises(module.CollectionFailure, match="collection_timeout"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, process)
    assert owner.calls.count("terminate") == 1
    assert owner.calls[-2:] == ["active", "close"]


def test_owner_termination_failure_preserves_primary_error_and_closes(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner()

    def fail_termination() -> bool:
        owner.calls.append("terminate")
        return False

    owner.terminate = fail_termination
    with pytest.raises(module.CollectionFailure, match=r"^collection_failed; cleanup_failed$"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, _Process(returncode=1))
    assert owner.calls[-1] == "close"


def test_unassigned_root_that_cannot_exit_preserves_activation_error_and_closes(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner(activated=False)
    process = _Process(timeout=True)
    process.poll = lambda: None
    process.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("collection", timeout))
    with pytest.raises(module.CollectionFailure, match=r"^owner_not_activated; cleanup_failed$"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, process)
    assert "terminate" in process.calls
    assert "kill" in process.calls
    assert owner.calls[-1] == "close"


def test_abort_owner_state_uncertainty_preserves_primary_error_and_closes(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner()
    owner.active = lambda: (_ for _ in ()).throw(OSError("query"))
    with pytest.raises(module.CollectionFailure, match=r"^collection_failed; cleanup_failed$"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, _Process(returncode=1))
    assert owner.calls[-1] == "close"


def test_missing_receipt_after_success_fails_and_cleans_owner(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner()
    with pytest.raises(module.CollectionFailure, match="collection_receipt_missing"):
        _install_supervisor(monkeypatch, module, tmp_path, owner, _Process())
    assert "terminate" in owner.calls
    assert owner.calls[-2:] == ["active", "close"]


@pytest.mark.parametrize("returncode", [1, 5])
def test_process_failure_is_not_overridden_by_success_receipt(monkeypatch, tmp_path, returncode) -> None:
    module = _load_driver()
    owner = _Owner()
    process = _Process(returncode=returncode)
    with pytest.raises(module.CollectionFailure, match="collection_failed"):
        _install_supervisor(
            monkeypatch,
            module,
            tmp_path,
            owner,
            process,
            receipt=lambda token: {"token": token, "collected": 10, "returncode": 0},
        )


def test_active_owner_after_success_is_terminated_and_fails(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner(active=True)
    process = _Process()
    with pytest.raises(module.CollectionFailure, match="owner_still_active"):
        _install_supervisor(
            monkeypatch,
            module,
            tmp_path,
            owner,
            process,
            receipt=lambda token: {"token": token, "collected": 10, "returncode": 0},
        )
    assert "terminate" in owner.calls


def test_owner_query_or_close_uncertainty_fails(monkeypatch, tmp_path) -> None:
    module = _load_driver()
    owner = _Owner(close=False)
    process = _Process()
    with pytest.raises(module.CollectionFailure, match="owner_close_failed"):
        _install_supervisor(
            monkeypatch,
            module,
            tmp_path,
            owner,
            process,
            receipt=lambda token: {"token": token, "collected": 10, "returncode": 0},
        )

    owner = _Owner()
    owner.active = lambda: (_ for _ in ()).throw(OSError("query"))
    with pytest.raises(module.CollectionFailure, match="owner_state_unavailable"):
        _install_supervisor(
            monkeypatch,
            module,
            tmp_path / "second",
            owner,
            _Process(),
            receipt=lambda token: {"token": token, "collected": 10, "returncode": 0},
        )
