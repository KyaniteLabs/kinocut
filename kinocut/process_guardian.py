"""Standalone POSIX supervisor for commands inside a detached leased worker.

A thread watches the worker-owned liveness pipe after the native command is
spawned/reaped through stdlib Popen. Normal commands leave no orphan watchdog.
The supervisor and native command retain the inherited flock lease until their
cleanup. Groups are lifecycle ownership, not a sandbox against setsid escapes.
"""

import contextlib
import errno
import os
import select
import signal
import subprocess
import sys
import threading


def _alive(pipe):
    ready, _, _ = select.select([pipe], [], [], 0)
    return not ready  # The parent never writes data; readability means EOF.


def _kill_group(group):
    if os.getpgrp() == group:
        os.killpg(group, signal.SIGKILL)
    os._exit(127)


def _watch(group, pipe):
    try:
        os.read(pipe, 1)  # Only the worker owns a writer; death/close means EOF.
    finally:
        _kill_group(group)


def _native_exit(returncode):
    if returncode < 0:
        signum = -returncode
        if signum not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    os._exit(returncode)


def main():
    # All arguments are private launcher-owned protocol fields, not user options.
    owner, pipe, error, _lease = map(int, sys.argv[1:5])
    inherited = tuple(map(int, sys.argv[5].split(","))) if sys.argv[5] else ()
    status = int(sys.argv[6])
    command = sys.argv[8:]
    group, child = os.getpid(), None
    try:
        if sys.argv[7] != "--" or not command or os.getpgrp() != group or os.getppid() != owner or not _alive(pipe):
            os._exit(127)
        # Spawn before starting ANY thread; the parent's threaded code never
        # uses preexec_fn. The native child inherits controlled stdio and FDs.
        child = subprocess.Popen(  # noqa: S603 - trusted argv; outer owner bounds wait/cleanup.
            command, stdin=0, stdout=1, stderr=2, close_fds=True, pass_fds=inherited
        )
        watcher = threading.Thread(target=_watch, args=(group, pipe), daemon=True)
        watcher.start()
        os.write(error, b"R")
        os.close(error)
        returncode = child.wait()
        if status >= 0:
            os.write(status, b"C" + str(returncode).encode("ascii"))
            os.close(status)
            watcher.join()  # Parent cleanup kills this still-owned live group.
        _native_exit(returncode)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.write(error, b"E" + str(exc.errno or errno.EIO).encode("ascii"))
        if child is not None:
            _kill_group(group)
        os._exit(127)
    except BaseException:
        # Startup/thread failure must not strand an already executing child.
        with contextlib.suppress(OSError):
            os.write(error, b"E" + str(errno.EIO).encode("ascii"))
        _kill_group(group)


if __name__ == "__main__":
    main()
