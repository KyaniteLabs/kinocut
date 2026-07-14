"""S14 bounded local pool scheduler with cancel/resume ceilings."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class CancelledError(RuntimeError):
    """Raised when a task or map is cancelled."""


@dataclass(frozen=True)
class PoolLimits:
    max_workers: int = 4
    max_tasks: int = 256
    max_wall_seconds: float = 1800.0


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    ok: bool
    value: Any = None
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass
class BoundedProcessPool:
    limits: PoolLimits = field(default_factory=PoolLimits)
    completed_ids: set[str] = field(default_factory=set)
    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancel(self) -> None:
        self._cancelled = False

    def map_tasks(
        self,
        tasks: Iterable[tuple[str, Callable[[], T]]],
        *,
        skip_completed: bool = True,
    ) -> list[TaskResult]:
        prepared = list(tasks)
        if len(prepared) > self.limits.max_tasks:
            raise ValueError(f"task count {len(prepared)} exceeds ceiling {self.limits.max_tasks}")
        if self._cancelled:
            raise CancelledError("pool cancelled before start")

        pending: list[tuple[str, Callable[[], T]]] = []
        results: list[TaskResult] = []
        for task_id, fn in prepared:
            if skip_completed and task_id in self.completed_ids:
                results.append(TaskResult(task_id=task_id, ok=True, value="skipped"))
                continue
            pending.append((task_id, fn))

        start = time.perf_counter()
        workers = max(1, min(self.limits.max_workers, len(pending) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Future[Any], str] = {}
            for task_id, fn in pending:
                if self._cancelled:
                    break
                if time.perf_counter() - start > self.limits.max_wall_seconds:
                    break
                futures[pool.submit(self._run_one, task_id, fn)] = task_id

            done, not_done = wait(futures.keys(), timeout=self.limits.max_wall_seconds)
            for fut in not_done:
                fut.cancel()
                results.append(
                    TaskResult(
                        task_id=futures[fut],
                        ok=False,
                        error="wall_timeout_or_cancelled",
                    )
                )
            for fut in done:
                results.append(fut.result())

        for r in results:
            if r.ok and r.value != "skipped":
                self.completed_ids.add(r.task_id)
        return results

    def _run_one(self, task_id: str, fn: Callable[[], T]) -> TaskResult:
        if self._cancelled:
            return TaskResult(task_id=task_id, ok=False, error="cancelled")
        t0 = time.perf_counter()
        try:
            value = fn()
            return TaskResult(
                task_id=task_id,
                ok=True,
                value=value,
                elapsed_seconds=time.perf_counter() - t0,
            )
        except Exception as exc:
            return TaskResult(
                task_id=task_id,
                ok=False,
                error=type(exc).__name__,
                elapsed_seconds=time.perf_counter() - t0,
            )
