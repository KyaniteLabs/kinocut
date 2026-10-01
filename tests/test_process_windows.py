"""Native Job Object ABI ownership and failure cleanup, executable on Linux."""

from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.process_windows import WindowsJob


class Kernel:
    def __init__(self, fail=None):
        self.calls, self.closed, self.fail = [], [], fail

    def CreateJobObjectW(self, *args):
        return 100

    def SetInformationJobObject(self, handle, kind, pointer, size):
        self.calls.append(("limits", kind, pointer._obj.basic.flags))
        return self.fail != "limits"

    def AssignProcessToJobObject(self, handle, process):
        self.calls.append(("assign", process))
        return self.fail != "assign"

    def CreateToolhelp32Snapshot(self, flags, pid):
        assert flags == 4
        return 200

    def Thread32First(self, snapshot, entry):
        entry._obj.owner_pid, entry._obj.thread_id = 123, 456
        return 1

    def Thread32Next(self, *args):
        return 0

    def OpenThread(self, rights, inherit, tid):
        assert (rights, inherit, tid) == (2, False, 456)
        return 300

    def ResumeThread(self, handle):
        self.calls.append(("resume", handle))
        return 0xFFFFFFFF if self.fail == "resume" else 1

    def TerminateJobObject(self, handle, status):
        self.calls.append(("terminate", handle))
        return 1

    def QueryInformationJobObject(self, handle, kind, pointer, size, required):
        pointer._obj.active_processes = 0
        self.calls.append(("quiescent", handle))
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


def test_job_disallows_breakaway_assigns_before_resuming_and_checks_quiescence():
    kernel = Kernel()
    job = WindowsJob(kernel)
    job.attach(SimpleNamespace(pid=123, _handle=99))
    job.stop()
    job.close()
    assert kernel.calls == [
        ("limits", 9, 0x2000),
        ("assign", 99),
        ("resume", 300),
        ("terminate", 100),
        ("quiescent", 100),
    ]
    assert kernel.closed == [300, 200, 100]


@pytest.mark.parametrize("failure", ["limits", "assign", "resume"])
def test_job_errors_close_owned_handles_and_do_not_resume_unowned_child(failure):
    kernel = Kernel(failure)
    job = None
    try:
        with pytest.raises(MCPVideoError) as error:
            job = WindowsJob(kernel)
            job.attach(SimpleNamespace(pid=123, _handle=99))
        assert error.value.code == "process_ownership_unavailable"
    finally:
        if job:
            job.close()
    assert 100 in kernel.closed
    if failure == "assign":
        assert not any(call[0] == "resume" for call in kernel.calls)
    if failure == "resume":
        assert {200, 300}.issubset(kernel.closed)
