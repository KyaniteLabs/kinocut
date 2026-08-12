"""Track E formal GO: cutfile render surface, sessions with receipt, CI action shape."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kinocut.te import (
    init_project,
    render_cutfile,
    session_close,
    session_open,
    session_step,
)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_cutfile_render_end_to_end(tmp_path: Path, sample_video: str) -> None:
    root = tmp_path / "proj"
    init_project(str(root), name="te-go", with_cutfile=True)
    media = root / "media" / "hero.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_video, media)
    cutfile = {
        "name": "te-go",
        "version": 1,
        "sources": [{"id": "hero", "path": "media/hero.mp4"}],
        "ops": [
            {"op": "trim", "start": 0, "duration": 1},
            {"op": "resize", "width": 320, "height": 240},
        ],
    }
    (root / "cutfile.json").write_text(json.dumps(cutfile), encoding="utf-8")
    result = render_cutfile(str(root / "cutfile.json"), output_path="out/final.mp4")
    assert result["artifact_kind"] == "cutfile_render"
    assert Path(result["output_path"]).is_file()
    assert result["workflow"]["status"] == "completed"


def test_edit_session_measured_improvement_and_receipt(tmp_path: Path) -> None:
    opened = session_open(str(tmp_path / "sess"), goal="tighten cut")
    session_path = opened["path"]
    session_step(session_path, action="trim silence", score=0.4)
    session_step(session_path, action="fix pacing", score=0.7)
    closed = session_close(session_path)
    assert closed["measured_improvement"] == pytest.approx(0.3)
    assert closed["receipt_path"]
    receipt = json.loads(Path(closed["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["artifact_kind"] == "edit_session_receipt"
    assert receipt["measured_improvement"] == pytest.approx(0.3)
    assert receipt["step_count"] == 2


def test_kinocut_video_ci_action_writes_receipt_contract() -> None:
    action = Path(".github/actions/kinocut-video-ci/action.yml").read_text(encoding="utf-8")
    assert "video-ci.receipt.json" in action or "Write receipt" in action
    assert "metric-qc" in action or "review-run" in action
    assert "cutfile-render" in action
