"""The task benchmark counts what it claims to count, without a model or a server."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("task_benchmark", ROOT / "scripts" / "task_benchmark.py")
bench = importlib.util.module_from_spec(_spec)
sys.modules["task_benchmark"] = bench
_spec.loader.exec_module(bench)


def _text_result(payload: object, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))], isError=is_error)


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict) -> SimpleNamespace:
        self.calls.append(name)
        if name == "boom":
            raise RuntimeError("server went away")
        if name == "bad":
            return _text_result({"success": False, "error": {"code": "invalid_parameter"}})
        return _text_result({"success": True, "output_path": "out.mp4"})


def _run(script: list[tuple[str, dict]]) -> tuple[object, FakeSession]:
    row = bench.TaskResult("local", "scripted", "trim", False)
    session = FakeSession()
    asyncio.run(bench.run_task(session, bench.ScriptedModel(script), [], "trim it", row))
    return row, session


def test_counts_calls_and_retries() -> None:
    row, session = _run([("bad", {}), ("boom", {}), ("good", {})])
    assert session.calls == ["bad", "boom", "good"]
    assert (row.calls, row.retries, row.turns) == (3, 2, 4)
    assert row.input_tokens > 0 and row.error is None


def test_gives_up_after_max_turns() -> None:
    row, _ = _run([("good", {})] * (bench.MAX_TURNS + 3))
    assert row.calls == bench.MAX_TURNS
    assert row.error == f"gave up after {bench.MAX_TURNS} turns"


@pytest.mark.parametrize(
    ("result", "failed"),
    [
        (_text_result({"success": True}), False),
        (_text_result({"success": False}), True),
        (_text_result({"error": "x"}), True),
        (_text_result({"ok": 1}, is_error=True), True),
        (SimpleNamespace(content=[SimpleNamespace(text="plain words")], isError=False), False),
    ],
)
def test_result_text_reads_failures_like_an_agent(result: SimpleNamespace, failed: bool) -> None:
    assert bench.result_text(result)[1] is failed


def test_catalogue_has_twenty_distinct_edits() -> None:
    assert len(bench.TASKS) == 20
    assert len({t.id for t in bench.TASKS}) == 20
    assert len({t.output for t in bench.TASKS}) == 20
    assert all("{src}" in t.prompt for t in bench.TASKS)


def test_checks_judge_probes() -> None:
    source = {
        "format": {"duration": "10.0", "size": "1000"},
        "streams": [
            {"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "30/1"},
            {"codec_type": "audio"},
        ],
    }
    trimmed = {"format": {"duration": "3.04", "size": "300"}, "streams": source["streams"]}
    tasks = {t.id: t for t in bench.TASKS}
    assert tasks["trim"].check(trimmed, source)
    assert not tasks["trim"].check(source, source)
    assert tasks["compress"].check(trimmed, source)
    assert not tasks["mute"].check(source, source)


def test_task_passed_is_false_for_a_missing_file(tmp_path: Path) -> None:
    assert bench.task_passed(bench.TASKS[0], tmp_path / "nope.mp4", {}) is False


def test_report_table() -> None:
    rows = [
        bench.TaskResult("2.0", "m", "trim", True, 100, 20, 2, 0, 3),
        bench.TaskResult("2.0", "m", "resize", False, 300, 40, 4, 2, 5),
        bench.TaskResult("1.16.5", "m", "trim", True, 900, 50, 3, 1, 4),
    ]
    table = bench.markdown_table(bench.summarize(rows))
    assert "| 2.0 | m | 1/2 | 230 | 3.0 | 2 |" in table
    assert "| 1.16.5 | m | 1/1 | 950 | 3.0 | 1 |" in table


def test_cli_rejects_bad_specs() -> None:
    with pytest.raises(SystemExit):
        bench.parse_server("no-equals-sign")
    with pytest.raises(SystemExit):
        bench.build_model("gemini:x")
    with pytest.raises(SystemExit):
        bench.main([])
