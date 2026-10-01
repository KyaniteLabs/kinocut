"""Observe POSIX completion while retaining the child's kernel identity."""

import os

from .errors import MCPVideoError


def supports_nonreaping_wait():
    return all(hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT"))


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
