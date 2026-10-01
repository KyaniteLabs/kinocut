"""Self-stop authority cannot be inherited or inferred from reusable PIDs."""

from __future__ import annotations

import os
import signal
import threading
from types import SimpleNamespace

import pytest

from kinocut.projectstore import render_control, render_jobs
from tests.test_projectstore_render_cancel import _job


def test_wait_only_controller_never_signals_reused_leader_pid(monkeypatch):
    signals = []
    monkeypatch.setattr(render_control, "group_quiescent", lambda _: False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args), raising=False)
    monkeypatch.setattr(os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(render_control, "DEFAULT_RENDER_STOP_TIMEOUT", 0.01)
    assert render_control.stop_runner_group(424242, lambda: True) == "timeout"
    assert signals == []


def test_wait_only_controller_rejects_nonleader_identity_without_signals(monkeypatch):
    signals = []
    monkeypatch.setattr(render_control, "group_quiescent", lambda _: False)
    monkeypatch.setattr(os, "getpgid", lambda _: 777777, raising=False)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args), raising=False)
    assert render_control.stop_runner_group(424242, lambda: True) == "identity_unverified"
    assert signals == []


@pytest.mark.parametrize("final_quiescent,final_lease_held", [(True, False), (False, False), (True, True)])
def test_worker_self_stop_between_initial_group_and_lease_checks(monkeypatch, final_quiescent, final_lease_held):
    signals = []
    quiescence = iter([False, final_quiescent])
    lease = iter([False, final_lease_held])
    monkeypatch.setattr(render_control, "group_quiescent", lambda _: next(quiescence))
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args), raising=False)
    monkeypatch.setattr(os, "kill", lambda *args: signals.append(args))
    outcome = render_control.stop_runner_group(424242, lambda: next(lease))
    assert outcome == ("stopped" if final_quiescent and not final_lease_held else "identity_unverified")
    assert signals == []


def test_disappeared_worker_waits_for_inherited_guardian_lease(monkeypatch):
    signals = []
    leased = iter([True, True, True, False])
    monkeypatch.setattr(render_control, "group_quiescent", lambda _: True)
    monkeypatch.setattr(os, "getpgid", lambda _: (_ for _ in ()).throw(ProcessLookupError()), raising=False)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args), raising=False)
    assert render_control.stop_runner_group(424242, lambda: next(leased)) == "stopped"
    assert signals == []


def test_observer_caches_validated_head_until_journal_changes(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    owner = os.getpid()
    render_jobs.mark_running(project, job.job_id, owner)
    real_read = render_jobs.get_render_job
    reads = []

    def read(*args):
        reads.append(args)
        return real_read(*args)

    monkeypatch.setattr(render_jobs, "get_render_job", read)
    observe = render_jobs._runner_stop_observer(project, job.job_id, owner)
    for _ in range(50):
        assert not observe()
    assert len(reads) == 1
    render_jobs.cancel_render_job(project, job.job_id)  # self-PID stays pending; no signals
    assert observe()
    assert len(reads) == 2
    assert observe()
    assert len(reads) == 2


def test_observer_refuses_inherited_fork_activation(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    owner = os.getpid()
    observe = render_jobs._runner_stop_observer(project, job.job_id, owner)
    monkeypatch.setattr(os, "getpid", lambda: owner + 1)
    monkeypatch.setattr(render_jobs, "get_render_job", lambda *_: pytest.fail("fork acquired journal authority"))
    assert not observe()


def test_observer_refuses_stop_journal_for_a_different_runner(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    owner = os.getpid()
    render_jobs.mark_running(project, job.job_id, owner)
    render_jobs.cancel_render_job(project, job.job_id)
    head = render_jobs.get_render_job(project, job.job_id)
    monkeypatch.setattr(
        render_jobs,
        "get_render_job",
        lambda *_: SimpleNamespace(
            status=head.status,
            stage=head.stage,
            runner_pid=owner + 1,
        ),
    )
    assert not render_jobs._runner_stop_observer(project, job.job_id, owner)()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private session identity")
@pytest.mark.parametrize("group_delta,session_delta", [(1, 0), (0, 1)])
def test_self_stop_refuses_nonprivate_group_or_session(monkeypatch, group_delta, session_delta):
    owner = os.getpid()
    signals = []
    monkeypatch.setattr(os, "getpgrp", lambda: owner + group_delta)
    monkeypatch.setattr(os, "getsid", lambda _: owner + session_delta)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))
    assert not render_control._stop_current_runner(owner)
    assert signals == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX private session identity")
def test_self_stop_signals_only_its_own_executing_private_group(monkeypatch):
    owner = os.getpid()
    signals = []
    monkeypatch.setattr(os, "getpgrp", lambda: owner)
    monkeypatch.setattr(os, "getsid", lambda _: owner)
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))
    assert render_control._stop_current_runner(owner)
    assert signals == [(owner, signal.SIGKILL)]


def test_watcher_consumes_request_and_finishes_its_thread(monkeypatch):
    requested = threading.Event()
    consumed = threading.Event()

    def stop(owner):
        assert owner == os.getpid()
        consumed.set()
        return True

    monkeypatch.setattr(render_control, "_stop_current_runner", stop)
    with render_control.watch_runner_stop(requested.is_set):
        requested.set()
        assert consumed.wait(timeout=2)
    assert not any(thread.name == "kinocut-render-stop" for thread in threading.enumerate())
