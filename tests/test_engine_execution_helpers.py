"""Guarded engine probes, weighted callbacks, and finalized edit receipts."""

import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut import bounded_process, engine_runtime_utils as runtime
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_progress import run_progress
from kinocut.models import EditResult


def test_filter_probe_and_thumbnail_own_their_process_trees(sample_video, monkeypatch):
    trees = []
    build_tree = bounded_process.ProcessTree

    def record_tree(*args, **kwargs):
        tree = build_tree(*args, **kwargs)
        trees.append(tree)
        return tree

    monkeypatch.setattr(bounded_process, "ProcessTree", record_tree)
    monkeypatch.setattr(runtime, "_AVAILABLE_FILTERS", None)
    assert runtime._check_filter_available("scale")
    assert runtime._check_filter_available("scale")
    assert base64.b64decode(runtime._generate_thumbnail_base64(sample_video)).startswith(b"\xff\xd8")
    assert len(trees) == 2
    for tree in trees:
        assert tree.closed and tree.process.poll() == 0
        assert tree.process.stdout.closed and tree.process.stderr.closed
        if os.name == "posix":
            assert tree.guardian is not None


def test_weighted_progress_maps_stage_boundaries_and_clamps():
    values = []
    progress = runtime.StagedProgress(values.append, 1, 3)
    first, second = progress.stage(0), progress.stage(1)
    for percent in (-1, 50, 101):
        first(percent)
    for percent in (-1, 50, 101):
        second(percent)
    assert values == [0, 12.5, 25, 25, 62.5, 100]
    assert runtime.StagedProgress(None, 1, 3).stage(0) is None


def test_weighted_progress_never_moves_backward_on_regressing_timestamps():
    values: list[float] = []
    progress = runtime.StagedProgress(values.append, 1, 3)
    script = "import sys; sys.stderr.write('time=00:00:08.00\\ntime=00:00:04.00\\n'); sys.stderr.flush()"

    def parse_time(ts: str) -> float:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    run_progress([sys.executable, "-c", script], 10.0, progress.stage(0), parse_time)
    run_progress([sys.executable, "-c", script], 10.0, progress.stage(1), parse_time)

    assert values == [20.0, 20.0, 25.0, 85.0, 85.0, 100.0]
    assert values == sorted(values)


@pytest.mark.parametrize("code", ["process_cleanup_failed", "process_ownership_unavailable"])
def test_thumbnail_base64_propagates_process_ownership_and_cleanup_failures(monkeypatch, code):
    def fail_bounded(*args, **kwargs):
        raise MCPVideoError(f"injected {code}", code=code)

    monkeypatch.setattr(runtime, "run_bounded", fail_bounded)
    with pytest.raises(MCPVideoError) as exc:
        runtime._generate_thumbnail_base64("dummy.mp4")
    assert exc.value.code == code


def test_thumbnail_base64_still_swallows_ordinary_failures(monkeypatch):
    def fail_bounded(*args, **kwargs):
        raise RuntimeError("corrupt frame")

    monkeypatch.setattr(runtime, "run_bounded", fail_bounded)
    assert runtime._generate_thumbnail_base64("dummy.mp4") is None


def test_transaction_finalizes_path_and_elapsed_only_after_publish(tmp_path, monkeypatch):
    destination = tmp_path / "final.mp4"
    times = iter([5.0, 5.25])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(times)))
    staged_results = []

    def render(staged):
        Path(staged).write_bytes(b"edited")

    def postflight(staged):
        assert not destination.exists() and Path(staged).read_bytes() == b"edited"
        result = EditResult(output_path=staged, operation="test")
        staged_results.append(result)
        return result

    result = runtime._transactional_edit(str(destination), "test", render, build_result=postflight)
    assert result.output_path == str(destination)
    assert result.elapsed_ms == 250
    assert destination.read_bytes() == b"edited"
    assert not Path(staged_results[0].output_path).exists()
    assert staged_results[0].elapsed_ms is None


def test_transaction_does_not_publish_when_postflight_fails(tmp_path):
    destination = tmp_path / "final.mp4"

    def render(staged):
        Path(staged).write_bytes(b"edited")

    def postflight(staged):
        raise RuntimeError("postflight failed")

    with pytest.raises(RuntimeError, match="postflight failed"):
        runtime._transactional_edit(str(destination), "test", render, build_result=postflight)

    assert not list(tmp_path.iterdir())
