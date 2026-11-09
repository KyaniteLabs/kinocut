"""Content profiles for intentionally dark and light UI screen captures."""

from __future__ import annotations

import subprocess

import pytest

from kinocut import Client
from kinocut.cli.parser import build_parser
from kinocut.errors import MCPVideoError
from kinocut.quality_guardrails import quality_check
from kinocut.server_tools_ai import video_quality_check, video_release_checkpoint

_INDEPENDENT_CHECKS = ("audio_levels", "temporal_motion", "color_balance")


def _render_ui(path, ground: str, panels: tuple[tuple[int, int, int, int, str], ...]) -> None:
    """Flat UI panels on a neutral ground, with release-legal sine audio."""
    boxes = ",".join(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill" for x, y, w, h, color in panels)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={ground}:s=640x360:d=1:r=8",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=1",
        "-vf",
        boxes,
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-400:])


def _dark_ui(path) -> None:
    _render_ui(
        path,
        "0x121212",
        (
            (0, 0, 180, 360, "0x1b1b1b"),
            (200, 28, 400, 36, "0x222222"),
            (200, 84, 400, 240, "0x181818"),
        ),
    )


def _light_ui(path) -> None:
    _render_ui(
        path,
        "0xf2f2f2",
        (
            (0, 0, 180, 360, "0xe8e8e8"),
            (200, 28, 400, 36, "0xdedede"),
            (200, 84, 400, 240, "0xf6f6f6"),
        ),
    )


def _check(report: dict, name: str) -> dict:
    return next(item for item in report["checks"] if item["name"] == name)


def _assert_profile_independent(default: dict, profiled: dict) -> None:
    assert default["analysis_domain"] == profiled["analysis_domain"]
    for name in _INDEPENDENT_CHECKS:
        assert _check(default, name) == _check(profiled, name)


def test_dark_ui_fails_default_gate_and_passes_ui_capture_dark(tmp_path):
    video = tmp_path / "dark-ui.mp4"
    _dark_ui(video)

    default = quality_check(str(video))
    profiled = quality_check(str(video), profile="ui-capture-dark")

    brightness = _check(default, "brightness")["details"]
    assert brightness["y_avg"] < 40
    assert _check(default, "contrast")["details"]["y_std"] < 20
    assert _check(default, "saturation")["details"]["saturation_pct"] < 10
    assert default["overall_score"] < 80
    assert "profile" not in default
    measured = {"brightness": "y_avg", "contrast": "y_std", "saturation": "saturation_pct"}
    for name, metric in measured.items():
        assert _check(default, name)["passed"] is False
        assert _check(profiled, name)["passed"] is True
        assert _check(default, name)["details"][metric] == _check(profiled, name)["details"][metric]

    assert profiled["profile"] == "ui-capture-dark"
    assert profiled["overall_score"] >= 80
    _assert_profile_independent(default, profiled)

    blocked = video_release_checkpoint(str(video), output_dir=str(tmp_path / "blocked"), frame_count=2)
    assert blocked["success"] is False
    assert blocked["error"]["code"] == "quality_gate_failed"
    assert not (tmp_path / "blocked").exists()

    receipt = video_release_checkpoint(
        str(video),
        output_dir=str(tmp_path / "review"),
        profile="ui-capture-dark",
        frame_count=2,
    )
    assert receipt["success"] is True
    assert receipt["profile"] == "ui-capture-dark"
    assert receipt["quality"]["profile"] == "ui-capture-dark"
    assert receipt["quality"]["gate_passed"] is True
    assert receipt["quality"]["overall_score"] >= 80
    assert receipt["review_required"] is True


def test_light_ui_fails_default_gate_and_passes_ui_capture_light(tmp_path):
    video = tmp_path / "light-ui.mp4"
    _light_ui(video)

    default = quality_check(str(video))
    profiled = quality_check(str(video), profile="ui-capture-light")

    assert _check(default, "brightness")["details"]["y_avg"] > 200
    assert default["overall_score"] < 80
    assert "profile" not in default
    assert profiled["profile"] == "ui-capture-light"
    assert profiled["overall_score"] >= 80
    for name in ("brightness", "contrast", "saturation"):
        assert _check(profiled, name)["passed"] is True
    _assert_profile_independent(default, profiled)


def test_unknown_profile_is_rejected_before_analysis(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")

    with pytest.raises(MCPVideoError, match="Unknown quality content profile") as exc_info:
        quality_check(str(video), profile="camera")

    assert exc_info.value.code == "invalid_parameter"
    result = video_quality_check(str(video), profile="camera")
    assert result["success"] is False
    assert result["error"]["code"] == "invalid_parameter"


def test_quality_commands_accept_only_known_profiles():
    parser = build_parser()
    dark = parser.parse_args(["video-quality-check", "clip.mp4", "--profile", "ui-capture-dark"])
    light = parser.parse_args(["release-checkpoint", "clip.mp4", "--profile", "ui-capture-light"])
    omitted = parser.parse_args(["video-quality-check", "clip.mp4"])

    assert dark.profile == "ui-capture-dark"
    assert light.profile == "ui-capture-light"
    assert omitted.profile is None
    with pytest.raises(SystemExit):
        parser.parse_args(["video-quality-check", "clip.mp4", "--profile", "camera"])


def test_client_receipt_records_profile_and_default_omits_it(monkeypatch, tmp_path):
    editor = Client()
    video = tmp_path / "video.mp4"
    video.write_bytes(b"placeholder")
    seen: list[str | None] = []

    def fake_assert(input_path, min_score=80.0, require_audio=True, profile=None):
        seen.append(profile)
        report = {"overall_score": 91.0, "gate_passed": True}
        if profile is not None:
            report["profile"] = profile
        return report

    monkeypatch.setattr(editor, "assert_quality", fake_assert)
    monkeypatch.setattr(
        editor,
        "thumbnail",
        lambda input_path, output=None, **kwargs: editor._to_edit_result(output or "thumb.jpg", operation="thumbnail"),
    )
    monkeypatch.setattr(
        editor,
        "storyboard",
        lambda input_path, output_path=None, **kwargs: editor._to_edit_result(
            output_path or "storyboard.jpg", operation="storyboard"
        ),
    )

    plain = editor.release_checkpoint(str(video), output_dir=str(tmp_path / "plain"))
    chosen = editor.release_checkpoint(str(video), output_dir=str(tmp_path / "dark"), profile="ui-capture-dark")

    assert "profile" not in plain
    assert seen == [None, "ui-capture-dark"]
    assert chosen["profile"] == "ui-capture-dark"
    assert chosen["quality"]["profile"] == "ui-capture-dark"
