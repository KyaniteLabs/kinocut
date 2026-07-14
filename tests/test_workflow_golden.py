"""Golden SSIM smoke + render-coverage gaps (V1/V2/V3/V4).

These renders are real FFmpeg jobs (marked ``slow``). SSIM is used instead of
byte-equality so the checks tolerate cross-FFmpeg-build variance (the release's
honest-determinism principle) while still catching gross regressions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mcp_video.engine import compare_quality
from mcp_video.engine_composite_layers import composite_layers
from mcp_video.workflow import render_workflow, validate_workflow_spec

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
# Same-build renders measure SSIM 1.0; the margin tolerates cross-FFmpeg-build
# variance (SSIM golden vs byte-equality — see the reproducibility note).
SSIM_THRESHOLD = 0.95

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")


def _gen_source(path: Path, lavfi: str = "testsrc2=size=160x120:rate=10:duration=1") -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            lavfi,
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _render_workflow_golden(workspace: Path) -> Path:
    """probe -> trim -> resize -> add captioned output (font-free for stability)."""
    workspace = Path(workspace)
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "output").mkdir(parents=True, exist_ok=True)
    _gen_source(workspace / "input" / "src.mp4")
    spec = {
        "schema_version": 1,
        "name": "golden-workflow",
        "sources": {"src": {"path": "input/src.mp4"}},
        "steps": [
            {"id": "probe", "op": "probe", "inputs": {"src": "@sources.src"}},
            {
                "id": "trim",
                "op": "trim",
                "inputs": {"src": "@sources.src"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/t.mp4",
            },
            {
                "id": "resize",
                "op": "resize",
                "inputs": {"src": "@work/t.mp4"},
                "params": {"width": 120, "height": 120},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }
    (workspace / "job.json").write_text(json.dumps(spec), encoding="utf-8")
    render_workflow(str(workspace / "job.json"))
    return workspace / "output" / "final.mp4"


def _composite_golden_spec() -> dict:
    """bg video + a positioned, semi-opaque solid patch (structured golden)."""
    return {
        "canvas": {"width": 160, "height": 120, "background": "#101820", "fps": 10, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            {
                "id": "tint",
                "type": "solid",
                "color": "#3050ff",
                "opacity": 0.6,
                "width": 80,
                "height": 60,
                "position": {"x": 40, "y": 30},
            },
        ],
        "output": {"format": "mp4"},
    }


def _blend_spec(blend: str | None) -> dict:
    """bg video + a FULL-CANVAS opaque solid (the only geometry blend allows)."""
    tint: dict = {"id": "tint", "type": "solid", "color": "#3050ff", "position": {"x": 0, "y": 0}}
    if blend is not None:
        tint["blend"] = blend
    return {
        "canvas": {"width": 160, "height": 120, "background": "#101820", "fps": 10, "duration": 1.0},
        "layers": [
            {"id": "background", "type": "video", "src": "bg.mp4", "position": {"x": 0, "y": 0}},
            tint,
        ],
        "output": {"format": "mp4"},
    }


def _render_composite(workspace: Path, spec: dict, name: str = "composite.mp4") -> Path:
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    _gen_source(workspace / "bg.mp4")
    (workspace / "layers.json").write_text(json.dumps(spec), encoding="utf-8")
    out = workspace / name
    composite_layers(str(workspace / "layers.json"), output_path=str(out))
    return out


def _render_composite_golden(workspace: Path) -> Path:
    return _render_composite(workspace, _composite_golden_spec())


def _ssim(reference: Path, candidate: Path) -> float:
    result = compare_quality(str(reference), str(candidate), metrics=["ssim"])
    ssim = result.metrics.get("ssim")
    assert ssim is not None, "SSIM was not computed by ffmpeg"
    return ssim


# --- V1: golden SSIM smoke --------------------------------------------------


@pytest.mark.slow
def test_workflow_render_matches_golden(tmp_path):
    golden = GOLDEN_DIR / "workflow_final.mp4"
    assert golden.is_file(), "missing committed golden; regenerate tests/fixtures/golden/"
    fresh = _render_workflow_golden(tmp_path)
    ssim = _ssim(golden, fresh)
    assert ssim >= SSIM_THRESHOLD, f"workflow render regressed vs golden: ssim={ssim}"


@pytest.mark.slow
def test_composite_render_matches_golden(tmp_path):
    golden = GOLDEN_DIR / "composite.mp4"
    assert golden.is_file(), "missing committed golden; regenerate tests/fixtures/golden/"
    fresh = _render_composite_golden(tmp_path)
    ssim = _ssim(golden, fresh)
    assert ssim >= SSIM_THRESHOLD, f"composite render regressed vs golden: ssim={ssim}"


# --- V2: convert exercised as a real workflow op ----------------------------


@pytest.mark.slow
def test_convert_op_runs_end_to_end(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    _gen_source(tmp_path / "input" / "src.mp4")
    spec = {
        "schema_version": 1,
        "name": "convert-smoke",
        "sources": {"src": {"path": "input/src.mp4"}},
        "steps": [
            {
                "id": "conv",
                "op": "convert",
                "inputs": {"src": "@sources.src"},
                "params": {"format": "webm"},
                "output": "@outputs.out",
            },
        ],
        "outputs": {"out": {"path": "output/converted.webm"}},
    }
    (tmp_path / "job.json").write_text(json.dumps(spec), encoding="utf-8")
    receipt = render_workflow(str(tmp_path / "job.json"))
    out = tmp_path / "output" / "converted.webm"
    assert receipt["status"] == "completed"
    assert out.is_file() and out.stat().st_size > 0
    conv_step = next(s for s in receipt["steps"] if s["id"] == "conv")
    assert conv_step["status"] == "completed"
    assert conv_step["output_hash"].startswith("sha256:")


# --- V3: flagship example spec stays valid ----------------------------------


def test_flagship_example_spec_validates():
    job = Path(__file__).parent.parent / "examples" / "workflows" / "captioned-vertical-short" / "job.json"
    assert job.is_file(), "flagship example job.json is missing"
    verdict = validate_workflow_spec(str(job))
    assert verdict["valid"] is True
    assert verdict["ops"] == sorted(["probe", "trim", "resize", "add_text"])


# --- V4: blend mode changes pixels, not just the filtergraph string ---------


@pytest.mark.slow
def test_blend_multiply_changes_pixels_vs_normal(tmp_path):
    normal = _render_composite(tmp_path / "n", _blend_spec(None), name="normal.mp4")
    multiply = _render_composite(tmp_path / "m", _blend_spec("multiply"), name="multiply.mp4")
    ssim = _ssim(normal, multiply)
    assert ssim < 0.99, f"multiply blend did not change pixels vs normal (ssim={ssim})"
