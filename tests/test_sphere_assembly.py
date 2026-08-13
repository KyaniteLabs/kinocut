"""360 dual-cam assembly: probe, plan, storyboard, render, director plug."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.te import (
    decide_sphere_plan,
    detect_sphere_director,
    is_sphere_goal,
    probe_360_source,
    propose_360_assembly,
    propose_sphere_plan,
    render_sphere_plan,
    storyboard_sphere_plan,
    validate_sphere_plan,
)
from kinocut.te.sphere_director import apply_director, parse_director_json


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True, timeout=60)


def _flat_video(path: Path, *, size: str = "640x480") -> str:
    _run_ffmpeg(["-f", "lavfi", "-i", f"color=c=gray:s={size}:d=1", "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def _equirect_video(path: Path) -> str:
    """2:1 source: red left hemisphere, blue right hemisphere."""
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x320:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x320:d=1",
            "-filter_complex",
            "hstack=inputs=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return str(path)


def test_probe_accepts_equirect_and_rejects_insv_and_flat(tmp_path: Path) -> None:
    good = _equirect_video(tmp_path / "sphere.mp4")
    probed = probe_360_source(good)
    assert probed["projection"] == "equirect"
    assert probed["width"] == 640
    assert probed["height"] == 320
    assert probed["sha256"].startswith("sha256:")

    with pytest.raises(MCPVideoError, match="stitched") as insv:
        probe_360_source(str(tmp_path / "clip.insv"))
    assert insv.value.code == "not_insv_export"

    flat = _flat_video(tmp_path / "phone.mp4")
    with pytest.raises(MCPVideoError, match="equirect") as phone:
        probe_360_source(flat)
    assert phone.value.code == "not_360_equirect"


def test_desk_and_table_presets_and_schema(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    desk = propose_sphere_plan(source, preset="desk")
    assert desk["layout"] == "split"
    assert [cam["id"] for cam in desk["cameras"]] == ["talent", "screens"]
    assert desk["status"] == "proposed"
    validate_sphere_plan(desk)

    table = propose_sphere_plan(source, preset="table")
    assert table["layout"] == "switch"
    assert [cam["id"] for cam in table["cameras"]] == ["talent", "table"]
    assert table["cameras"][1]["pitch"] < 0

    with pytest.raises(MCPVideoError) as missing:
        validate_sphere_plan({**desk, "cameras": []})
    assert missing.value.code == "invalid_sphere_plan"

    with pytest.raises(MCPVideoError) as layout:
        validate_sphere_plan({**desk, "layout": "cube"})
    assert layout.value.code == "invalid_sphere_layout"

    bad_window = {**desk, "windows": [{"id": "w1", "start": 2, "end": 1, "cameras": ["talent"]}]}
    with pytest.raises(MCPVideoError):
        validate_sphere_plan(bad_window)

    with pytest.raises(MCPVideoError) as no_out:
        validate_sphere_plan({**desk, "output": {}})
    assert no_out.value.code in {"invalid_sphere_plan", "invalid_sphere_aspect"}
    with pytest.raises(MCPVideoError) as no_src:
        validate_sphere_plan({**desk, "source": {}})
    assert no_src.value.code == "invalid_sphere_plan"


def test_storyboard_writes_distinct_camera_stills(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    plan = propose_sphere_plan(source, preset="desk")
    boarded = storyboard_sphere_plan(plan, str(tmp_path / "board"))
    paths = [Path(item["path"]) for item in boarded["stills"]]
    assert len(paths) == 2
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths)
    assert paths[0].read_bytes() != paths[1].read_bytes()


def test_render_requires_approval_then_writes_split(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    plan = propose_sphere_plan(source, preset="desk", aspect="16:9")
    dest = str(tmp_path / "out.mp4")
    with pytest.raises(MCPVideoError) as pending:
        render_sphere_plan(plan, dest, work_dir=str(tmp_path / "work"), allow_fail=True)
    assert pending.value.code == "human_apply_required"

    approved = decide_sphere_plan(plan, "approve")
    receipt = render_sphere_plan(approved, dest, work_dir=str(tmp_path / "work"), allow_fail=True)
    assert Path(dest).is_file()
    assert receipt["layout"] == "split"
    assert receipt["writer"]["kind"] == "heuristic"
    assert receipt["source"]["sha256"] == plan["source"]["sha256"]


def test_switch_window_with_two_cameras_renders(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    plan = propose_sphere_plan(source, preset="desk")
    plan["layout"] = "switch"
    plan["windows"] = [
        {
            "id": "w1",
            "start": 0.0,
            "end": float(plan["source"]["duration_seconds"]),
            "cameras": ["talent", "screens"],
            "layout": "switch",
        }
    ]
    approved = decide_sphere_plan(plan, "approve")
    dest = str(tmp_path / "switch-multi.mp4")
    receipt = render_sphere_plan(approved, dest, work_dir=str(tmp_path / "sw"), allow_fail=True)
    assert Path(dest).is_file()
    assert receipt["layout"] == "switch"


@pytest.mark.parametrize("layout", ["switch", "pip", "single"])
def test_other_layouts_render(tmp_path: Path, layout: str) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    writer = "single" if layout == "single" else "heuristic"
    plan = propose_sphere_plan(source, preset="desk", layout=layout, writer_kind=writer)
    approved = decide_sphere_plan(plan, "approve", layout=layout)
    dest = str(tmp_path / f"{layout}.mp4")
    receipt = render_sphere_plan(approved, dest, work_dir=str(tmp_path / f"w-{layout}"), allow_fail=True)
    assert Path(dest).is_file()
    assert receipt["layout"] == layout


def test_local_director_valid_and_invalid_json(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")

    def good(plan: dict) -> dict:
        clone = json.loads(json.dumps(plan))
        clone["layout"] = "pip"
        return clone

    modeled = apply_director(source, director="ollama", model="qwen-vl", propose=good)
    assert modeled["writer"]["kind"] == "model"
    assert modeled["writer"]["provider"] == "ollama"
    assert modeled["layout"] == "pip"

    def bad(_plan: dict) -> dict:
        raise ValueError("not json")

    fallback = apply_director(source, director="ollama", propose=bad)
    assert fallback["writer"]["kind"] == "heuristic"
    assert fallback["writer"].get("unavailable") is True

    with pytest.raises(MCPVideoError) as dumped:
        parse_director_json("not-json")
    assert dumped.value.code == "capability_unavailable"


def test_cloud_director_requires_opt_in(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    with pytest.raises(MCPVideoError) as denied:
        apply_director(source, director="openai", propose=lambda plan: plan)
    assert denied.value.code == "cloud_execution_denied"

    allowed = apply_director(source, director="openai", model="gpt-4o", allow_cloud=True, propose=lambda plan: plan)
    assert allowed["writer"]["kind"] == "model"
    assert allowed["writer"]["provider"] == "openai"
    assert allowed["writer"]["model"] == "gpt-4o"


def test_intent_goal_and_doctor_honesty(tmp_path: Path) -> None:
    source = _equirect_video(tmp_path / "sphere.mp4")
    assert is_sphere_goal("desk 360 split 9:16")
    plan = propose_360_assembly(source, goal="desk 360 split 9:16")
    assert plan["artifact_kind"] == "360_assembly_plan"
    assert plan["layout"] == "split"
    assert plan["output"]["aspect"] == "9:16"

    from kinocut.server_tools_intent import video_intent

    payload = video_intent(verb="reformat_vertical", goal="desk 360 split 9:16", source=source)
    assert payload["sphere_plan"]["artifact_kind"] == "360_assembly_plan"

    from kinocut.doctor import run_diagnostics

    report = run_diagnostics()
    names = [item["name"] for item in report["checks"]]
    assert "sphere_director" in names
    detected = detect_sphere_director()
    assert "ollama" in detected["local_ids"]
    assert "openai" in detected["cloud_ids"]
