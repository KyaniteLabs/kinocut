"""Observe POSIX completion while retaining the child's kernel identity."""

import errno
import os
import sys

from .errors import MCPVideoError


def supports_nonreaping_wait():
    # Darwin exposes WNOWAIT but denies killpg when only the retained zombie
    # remains. Keep a live supervisor there so group cleanup retains authority.
    if sys.platform == "darwin" or not all(
        hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT")
    ):
        return False
    # Probe waitid(2) against our own PID so seccomp/container filters returning
    # ENOSYS or EPERM fall back cleanly to the retaining supervisor mode.
    try:
        os.waitid(os.P_PID, os.getpid(), os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True
    except OSError as exc:
        return exc.errno not in {errno.ENOSYS, errno.EPERM}
    return True


def observe_exit(process) -> int | None:
    if process.returncode is not None:
        raise MCPVideoError("Owned child was reaped outside cleanup", code="process_ownership_unavailable")
    try:
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except OSError as exc:
        raise MCPVideoError("Owned child identity cannot be retained", code="process_ownership_unavailable") from exc
    if result is None or result.si_pid == 0:
        return None
    if result.si_pid != process.pid:
        raise MCPVideoError("Owned child identity changed", code="process_ownership_unavailable")
    return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
