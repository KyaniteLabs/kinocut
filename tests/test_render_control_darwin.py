"""Darwin group observations exclude zombies and retain unconfirmed work."""

import subprocess
from types import SimpleNamespace

import pytest

from kinocut.projectstore import render_control


@pytest.mark.parametrize(
    "output, expected",
    [
        ("101 101 Z\n102 101 ZN\n1 1 Ss\n", True),
        ("101 101 Z\n102 101 S\n", False),
        ("1 1 Ss\n", True),
        ("", False),
        ("101 invalid Z\n", False),
        ("101 101\n", False),
        ("101 101 Z extra\n", False),
        ("101 101 ?\n", False),
        ("0 101 Z\n", False),
    ],
)
def test_darwin_group_snapshot(monkeypatch, output, expected):
    def observe(argv, **kwargs):
        assert argv == ["/bin/ps", "-axo", "pid=,pgid=,stat="]
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] == render_control.DEFAULT_RENDER_STOP_TIMEOUT
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(render_control.subprocess, "run", observe)
    assert render_control._darwin_group_quiescent(101) is expected


@pytest.mark.parametrize("failure", [OSError(), subprocess.TimeoutExpired("ps", 1)])
def test_darwin_observation_failure_retains_work(monkeypatch, failure):
    def observe(*args, **kwargs):
        raise failure

    monkeypatch.setattr(render_control.subprocess, "run", observe)
    assert render_control._darwin_group_quiescent(101) is False


def test_darwin_nonzero_observation_retains_work(monkeypatch):
    monkeypatch.setattr(
        render_control.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess("ps", 1, "1 1 Ss", "")
    )
    assert render_control._darwin_group_quiescent(101) is False


@pytest.mark.parametrize("observed", [True, False])
def test_group_quiescent_dispatches_darwin_observation(monkeypatch, observed):
    pgid = render_control.os.getpid() + 1
    calls = []
    monkeypatch.setattr(render_control.sys, "platform", "darwin")
    monkeypatch.setattr(render_control.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(render_control, "Path", lambda _: SimpleNamespace(is_file=lambda: False))

    def observe(pid):
        calls.append(pid)
        return observed

    monkeypatch.setattr(render_control, "_darwin_group_quiescent", observe)
    monkeypatch.setattr(render_control.os, "killpg", lambda *_: pytest.fail("Darwin observation must not signal"))
    assert render_control.group_quiescent(pgid) is observed
    assert calls == [pgid]
