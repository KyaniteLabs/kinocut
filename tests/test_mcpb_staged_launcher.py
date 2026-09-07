"""Security and compatibility contracts for the staged MCPB launcher."""

from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "mcpb" / "server" / "launcher.js"
NODE = shutil.which("node")


def _ci_helper():
    path = ROOT / ".github" / "scripts" / "mcpb-ci.py"
    spec = importlib.util.spec_from_file_location("mcpb_ci_owner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node_eval(source: str, *args: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, "-e", source, str(LAUNCHER), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _launch_options(platform: str, supervised: bool) -> subprocess.CompletedProcess[str]:
    source = r"""
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const launcherPath = process.argv[1];
const source = fs.readFileSync(launcherPath, "utf8") + [
  "",
  "globalThis.__result = launch(",
  "  'configured python',",
  "  {KINOCUT_TEST_ENV: 'preserved'},",
  `  ${process.argv[3] === "true"},`,
  ");",
].join("\n");
let observed = null;
const child = {pid: 123};
function localRequire(name) {
  if (name === "node:child_process") {
    return {
      spawn(command, args, options) {
        observed = {command, args, options};
        return child;
      },
      spawnSync() { throw new Error("preflight spawn must not run"); },
    };
  }
  return require(name);
}
localRequire.main = {};
const context = {
  Buffer,
  __dirname: path.dirname(launcherPath),
  clearTimeout,
  console,
  module: {exports: {}},
  process: {env: {}, platform: process.argv[2]},
  require: localRequire,
  setTimeout,
};
vm.runInNewContext(source, context, {filename: launcherPath});
console.log(JSON.stringify({observed, sameChild: context.__result === child}));
"""
    return _node_eval(source, platform, str(supervised).lower())


class _OwnedSupervisor:
    kind = "test_owner"

    def __init__(self, *, close_ok: bool) -> None:
        self.close_ok = close_ok
        self.close_calls = 0
        self.terminate_calls = 0

    def environment(self) -> dict[str, str]:
        return {"KINOCUT_TEST_OWNER": "1"}

    def close(self) -> bool:
        self.close_calls += 1
        return self.close_ok

    def terminate(self) -> bool:
        self.terminate_calls += 1
        return True


def test_run_owned_demotes_owner_close_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _ci_helper()
    owner = _OwnedSupervisor(close_ok=False)
    monkeypatch.setattr(helper._owner_helper(), "create_owner", lambda _root: owner)
    monkeypatch.setattr(helper, "_run", lambda *_args, **_kwargs: "complete")

    with pytest.raises(helper.BoundedProcessError) as caught:
        helper._run_owned([sys.executable, "-c", "pass"], env={}, timeout=1)

    assert caught.value.classification == "owner_close_failed"
    assert caught.value.cleanup == "failed"
    assert owner.terminate_calls == 1
    assert owner.close_calls == 2


def test_run_owned_maps_owner_creation_failure_to_bounded_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _ci_helper()
    owner_module = helper._owner_helper()

    def fail_create(_root: Path) -> None:
        raise owner_module.OwnerActivationError("owner_not_activated", "failed")

    monkeypatch.setattr(owner_module, "create_owner", fail_create)

    with pytest.raises(helper.BoundedProcessError) as caught:
        helper._run_owned([sys.executable, "-c", "pass"], env={}, timeout=1)

    assert caught.value.classification == "owner_not_activated"
    assert caught.value.cleanup == "failed"


def _probe(candidate: str, version: str = "1.15.1", **options: int) -> subprocess.CompletedProcess[str]:
    source = """
const launcher = require(process.argv[1]);
const opts = JSON.parse(process.argv[4]);
launcher.probePython(process.argv[2], process.argv[3], opts)
  .then((result) => { console.log(JSON.stringify(result)); })
  .catch((error) => { console.error(error.message); process.exit(1); });
"""
    return _node_eval(source, candidate, version, json.dumps(options), timeout=15)


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX executable fixture required")
def test_launcher_accepts_exact_installed_python_and_path_with_spaces(tmp_path: Path) -> None:
    candidate = tmp_path / "python with spaces"
    candidate.write_text(f'#!/bin/sh\nexec {str(sys.executable)!r} "$@"\n', encoding="utf-8")
    candidate.chmod(0o755)

    result = _probe(str(candidate))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
    assert str(candidate) not in result.stderr


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_launcher_rejects_wrong_kinocut_version_without_stdout() -> None:
    result = _probe(sys.executable, "0.0.0")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"ok": False, "reason": "wrong_kinocut_version"}


def _write_probe_fixture(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX executable fixture required")
@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ('print(\'{"python":[3,10,9],"kinocut":"1.15.1"}\')', "python_too_old"),
        ('print(\'{"python":[3,11,0],"kinocut":null}\')', "kinocut_missing"),
        ("print('not-json')", "invalid_probe_output"),
        ("print('x' * 9000)", "probe_output_overflow"),
    ],
)
def test_launcher_classifies_bounded_probe_failures(tmp_path: Path, body: str, reason: str) -> None:
    candidate = tmp_path / "probe-python"
    _write_probe_fixture(candidate, body)

    result = _probe(str(candidate), maxOutputBytes=4096)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": False, "reason": reason}


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX process-group fixture required")
def test_launcher_timeout_kills_probe_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    candidate = tmp_path / "probe-python"
    _write_probe_fixture(
        candidate,
        f"""
        import subprocess, time
        child = subprocess.Popen([{sys.executable!r}, '-c', 'import time; time.sleep(60)'])
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(60)
        """,
    )

    result = _probe(str(candidate), timeoutMs=1000, killGraceMs=100)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": False, "reason": "probe_timeout"}
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not pid_file.exists():
        time.sleep(0.02)
    assert pid_file.is_file()
    descendant = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(descendant, 0)


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_launcher_exports_bounded_preflight_without_running_main() -> None:
    result = _node_eval(
        "const x=require(process.argv[1]); console.log(JSON.stringify(Object.keys(x).sort()))",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "loadRequiredVersion",
        "probeFailureMessage",
        "probePython",
        "pythonCandidates",
    ]
    assert result.stderr == ""


@pytest.mark.skipif(NODE is None, reason="Node is required")
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("python_not_startable", "could not be started"),
        ("python_too_old", "Python 3.11+"),
        ("kinocut_missing", "kinocut==1.15.1"),
        ("wrong_kinocut_version", "different Kinocut version"),
        ("invalid_probe_output", "invalid preflight response"),
        ("probe_failed", "preflight command failed"),
        ("probe_timeout", "timed out"),
        ("probe_output_overflow", "too much output"),
    ],
)
def test_launcher_maps_each_bounded_probe_failure_to_actionable_safe_text(reason: str, expected: str) -> None:
    source = "const x=require(process.argv[1]); console.log(x.probeFailureMessage(process.argv[2], '1.15.1'));"

    result = _node_eval(source, reason)

    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert "/private/" not in result.stdout and "\\Users\\" not in result.stdout


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX executable fixture required")
def test_launcher_main_reports_specific_preflight_failure_on_stderr_only(tmp_path: Path) -> None:
    candidate = tmp_path / "too-old-python"
    _write_probe_fixture(candidate, 'print(\'{"python":[3,10,9],"kinocut":"1.15.1"}\')')
    env = dict(os.environ)
    env["KINOCUT_MCPB_PYTHON"] = str(candidate)

    result = subprocess.run(
        [NODE, str(LAUNCHER)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False
    )

    assert result.returncode == 127
    assert result.stdout == ""
    assert "too old" in result.stderr and "Python 3.11+" in result.stderr
    assert str(candidate) not in result.stderr


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_launcher_main_reports_missing_configured_python_on_stderr_only(tmp_path: Path) -> None:
    missing = tmp_path / "private missing python"
    env = dict(os.environ)
    env["KINOCUT_MCPB_PYTHON"] = str(missing)

    result = subprocess.run(
        [NODE, str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 127
    assert result.stdout == ""
    assert "Configured Python could not be started" in result.stderr
    assert str(missing) not in result.stderr


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX executable fixture required")
def test_launcher_hands_off_to_exact_configured_python_as_one_executable(tmp_path: Path) -> None:
    candidate = tmp_path / "configured python with spaces"
    candidate.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then\n'
        '  printf \'%s\\n\' \'{"python":[3,11,0],"kinocut":"1.15.1"}\'\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "-m" ] && [ "$2" = "kinocut" ] && [ "$3" = "--mcp" ]; then\n'
        "  printf '%s\\n' 'exact-handoff'\n"
        "  exit 0\n"
        "fi\n"
        "exit 9\n",
        encoding="utf-8",
    )
    candidate.chmod(0o755)
    env = dict(os.environ)
    env["KINOCUT_MCPB_PYTHON"] = str(candidate)

    result = subprocess.run(
        [NODE, str(LAUNCHER)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "exact-handoff\n"
    assert result.stderr == ""


@pytest.mark.skipif(NODE is None, reason="Node is required")
@pytest.mark.parametrize(
    ("platform", "supervised", "detached"),
    [
        ("win32", False, False),
        ("win32", True, True),
        ("linux", False, True),
        ("linux", True, False),
    ],
)
def test_actual_server_spawn_selects_platform_and_supervision_mode(
    platform: str, supervised: bool, detached: bool
) -> None:
    result = _launch_options(platform, supervised)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sameChild"] is True
    assert payload["observed"] == {
        "command": "configured python",
        "args": ["-m", "kinocut", "--mcp"],
        "options": {
            "detached": detached,
            "stdio": "inherit",
            "env": {"KINOCUT_TEST_ENV": "preserved"},
            "shell": False,
        },
    }


@pytest.mark.skipif(NODE is None or os.name == "nt", reason="POSIX process-group fixture required")
def test_supervised_launcher_keeps_child_in_owner_group_and_records_redirector_identity(tmp_path: Path) -> None:
    candidate = tmp_path / "supervised-python"
    _write_probe_fixture(
        candidate,
        """
        import json, os, sys, time
        if sys.argv[1] == '-c':
            print(json.dumps({'python': [3, 11, 0], 'kinocut': '1.15.1'}))
        else:
            time.sleep(60)
        """,
    )
    observed = tmp_path / "server.json"
    token = "a" * 64
    env = dict(os.environ)
    env.update(
        KINOCUT_MCPB_PYTHON=str(candidate),
        KINOCUT_MCPB_SUPERVISED_PROCESS_TREE="1",
        KINOCUT_MCPB_SUPERVISED_PID_FILE=str(observed),
        KINOCUT_MCPB_SUPERVISED_TOKEN=token,
    )
    launcher = subprocess.Popen(
        [NODE, str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not observed.is_file():
            time.sleep(0.02)
        assert observed.is_file()
        payload = json.loads(observed.read_text(encoding="utf-8"))
        assert payload == {
            "token": token,
            "pid": payload["pid"],
            "role": "launcher_child",
            "phase": "spawned",
        }
        assert os.getpgid(payload["pid"]) == os.getpgid(launcher.pid)
    finally:
        os.killpg(launcher.pid, 9)
        launcher.wait(timeout=5)


@pytest.mark.skipif(NODE is None, reason="Node is required")
def test_launcher_main_rejects_invalid_ffmpeg_before_python_probe(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["KINOCUT_MCPB_FFMPEG"] = str(tmp_path / "not-ffmpeg")
    env["KINOCUT_MCPB_PYTHON"] = str(tmp_path / "must-not-run")

    result = subprocess.run(
        [NODE, str(LAUNCHER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 126
    assert result.stdout == ""
    assert "must point to an executable named ffmpeg" in result.stderr
    assert "Python 3.11" not in result.stderr
