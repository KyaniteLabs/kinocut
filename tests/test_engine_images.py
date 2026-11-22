"""Published 1.16.2 image-sequence regression coverage."""

from __future__ import annotations
import json
import subprocess
import sys
import pytest
from mcp_video.errors import MCPVideoError
from mcp_video.models import EditResult
from tests.image_sequence_fixtures import (
    _write_png,
    _probe_frames,
    _frame_hashes,
    _decode_rgb_frames,
    _mean_rgb,
    _color_distance,
    _unstaged_output,
    EXACT_RATES,
    SEQUENCE_COLORS,
    requires_ffmpeg,
)


@requires_ffmpeg
@pytest.mark.parametrize(("fps", "expected_rate"), EXACT_RATES)
@pytest.mark.parametrize("count", [1, 2, 90])
def test_output_has_exactly_one_frame_per_input(tmp_path, fps, expected_rate, count):
    images = [_write_png(tmp_path / f"frame_{i:04d}.png", 16, 16) for i in range(count)]
    output = str(tmp_path / "exact.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images(images, output_path=output, fps=fps)

    frames, rate = _probe_frames(output)
    assert frames == count
    assert rate == expected_rate


@requires_ffmpeg
@pytest.mark.parametrize(("fps", "expected_rate"), EXACT_RATES)
def test_each_input_maps_to_one_ordered_output_frame(tmp_path, fps, expected_rate):
    """Ten visually distinct inputs must stay unique and in input order."""
    images = [_write_png(tmp_path / f"frame_{i:04d}.png", 16, 16, rgb=color) for i, color in enumerate(SEQUENCE_COLORS)]
    output = str(tmp_path / "ordered.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images(images, output_path=output, fps=fps)

    frames, rate = _probe_frames(output)
    assert frames == len(SEQUENCE_COLORS)
    assert rate == expected_rate

    hashes = _frame_hashes(output)
    assert len(hashes) == len(SEQUENCE_COLORS)
    assert len(set(hashes)) == len(SEQUENCE_COLORS), "duplicate or dropped frame detected"

    decoded = _decode_rgb_frames(output, 16, 16)
    assert len(decoded) == len(SEQUENCE_COLORS)
    observed = [_mean_rgb(frame) for frame in decoded]
    for index, actual in enumerate(observed):
        distances = [_color_distance(actual, expected) for expected in SEQUENCE_COLORS]
        best_match = min(range(len(distances)), key=distances.__getitem__)
        assert best_match == index, (
            f"frame {index} decoded as input {best_match}: expected {SEQUENCE_COLORS[index]}, got {actual}"
        )


@requires_ffmpeg
def test_list_file_supplies_one_thousand_paths(tmp_path):
    images = [_write_png(tmp_path / f"frame_{i:04d}.png", 16, 16) for i in range(1000)]
    list_file = tmp_path / "frames.txt"
    list_file.write_text("\n\n" + "\n".join(images) + "\n\n", encoding="utf-8")
    output = str(tmp_path / "listed.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images(list_file=str(list_file), output_path=output, fps=30)

    frames, rate = _probe_frames(output)
    assert frames == 1000
    assert rate == "30/1"


def test_list_file_and_images_are_mutually_exclusive(tmp_path):
    image = _write_png(tmp_path / "frame.png", 10, 10)
    list_file = tmp_path / "frames.txt"
    list_file.write_text(image + "\n", encoding="utf-8")

    from mcp_video.engine_images import create_from_images

    with pytest.raises(MCPVideoError) as exc_info:
        create_from_images([image], list_file=str(list_file))

    assert exc_info.value.error_type == "validation_error"


def test_list_file_with_missing_image_is_rejected(tmp_path):
    list_file = tmp_path / "frames.txt"
    list_file.write_text(str(tmp_path / "missing.png") + "\n", encoding="utf-8")

    from mcp_video.engine_images import create_from_images

    with pytest.raises(MCPVideoError):
        create_from_images(list_file=str(list_file))


def test_empty_list_file_is_rejected(tmp_path):
    list_file = tmp_path / "frames.txt"
    list_file.write_bytes(b"\n\n   \n")

    from mcp_video.engine_images import create_from_images

    with pytest.raises(MCPVideoError) as exc_info:
        create_from_images(list_file=str(list_file))

    assert exc_info.value.code == "empty_images"


@requires_ffmpeg
def test_list_file_accepts_utf8_bom(tmp_path):
    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16) for i in range(2)]
    list_file = tmp_path / "frames.txt"
    list_file.write_bytes(b"\xef\xbb\xbf" + "\n".join(images).encode() + b"\n")
    output = str(tmp_path / "bom.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images(list_file=str(list_file), output_path=output, fps=24)

    frames, rate = _probe_frames(output)
    assert frames == 2
    assert rate == "24/1"


@pytest.mark.parametrize("fps", [True, False])
def test_boolean_frame_rates_are_rejected(fps, tmp_path):
    image = _write_png(tmp_path / "frame.png", 10, 10)

    from mcp_video.engine_images import create_from_images

    with pytest.raises(MCPVideoError) as exc_info:
        create_from_images([image], fps=fps)

    assert exc_info.value.error_type == "validation_error"


@requires_ffmpeg
def test_duplicate_input_path_produces_two_frames(tmp_path):
    image = _write_png(tmp_path / "same.png", 16, 16, rgb=(255, 0, 0))
    output = str(tmp_path / "duplicate.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images([image, image], output_path=output, fps=24)

    frames, rate = _probe_frames(output)
    assert frames == 2
    assert rate == "24/1"
    hashes = _frame_hashes(output)
    assert len(hashes) == 2
    assert len(set(hashes)) == 1


@pytest.mark.parametrize("fps", [0, -1, 61, "30000/0", "abc"])
def test_invalid_frame_rates_are_rejected(fps):
    from mcp_video.engine_images import create_from_images

    with pytest.raises(MCPVideoError) as exc_info:
        create_from_images(["/nonexistent/image.png"], fps=fps)

    assert exc_info.value.error_type == "validation_error"


def test_frame_rate_serialization_accepts_rationals():
    from mcp_video.engine_images import _coerce_fps

    assert _coerce_fps("30000/1001")[1] == "30000/1001"
    assert _coerce_fps("60/1")[1] == "60/1"
    assert _coerce_fps(30)[1] == "30"
    assert _coerce_fps(29.97002997)[1] == "29.97002997"


def test_even_dimension_pngs_skip_normalization(tmp_path, monkeypatch):
    from mcp_video import engine_images

    image = _write_png(tmp_path / "even.png", 10, 10)
    calls = {"normalize": 0}

    def fake_normalize(images, tmpdir):
        calls["normalize"] += 1
        return images

    monkeypatch.setattr(engine_images, "_normalize_images", fake_normalize)
    monkeypatch.setattr(engine_images, "_run_ffmpeg", lambda args: None)
    monkeypatch.setattr(engine_images, "_verify_output_frame_count", lambda path, expected: None)
    monkeypatch.setattr(engine_images, "_atomic_output", _unstaged_output)
    monkeypatch.setattr(
        engine_images,
        "_build_edit_result",
        lambda output, operation, timing: EditResult(output_path=output, operation=operation),
    )

    engine_images.create_from_images([image], output_path=str(tmp_path / "even.mp4"), fps=30)

    assert calls["normalize"] == 0


def test_odd_dimension_pngs_are_normalized(tmp_path, monkeypatch):
    from mcp_video import engine_images

    image = _write_png(tmp_path / "odd.png", 11, 11)
    calls = {"normalize": 0}

    def fake_normalize(images, tmpdir):
        calls["normalize"] += 1
        return images

    monkeypatch.setattr(engine_images, "_normalize_images", fake_normalize)
    monkeypatch.setattr(engine_images, "_run_ffmpeg", lambda args: None)
    monkeypatch.setattr(engine_images, "_verify_output_frame_count", lambda path, expected: None)
    monkeypatch.setattr(engine_images, "_atomic_output", _unstaged_output)
    monkeypatch.setattr(
        engine_images,
        "_build_edit_result",
        lambda output, operation, timing: EditResult(output_path=output, operation=operation),
    )

    engine_images.create_from_images([image], output_path=str(tmp_path / "odd.mp4"), fps=30)

    assert calls["normalize"] == 1


@requires_ffmpeg
def test_odd_dimension_inputs_are_normalized_into_ordered_sequence(tmp_path):
    colors = SEQUENCE_COLORS[:3]
    images = [_write_png(tmp_path / f"odd_{i}.png", 11, 11, rgb=color) for i, color in enumerate(colors)]
    output = str(tmp_path / "odd_sequence.mp4")

    from mcp_video.engine_images import create_from_images

    create_from_images(images, output_path=output, fps=25)

    frames, rate = _probe_frames(output)
    assert frames == len(colors)
    assert rate == "25/1"

    decoded = _decode_rgb_frames(output, 10, 10)
    assert len(decoded) == len(colors)
    for index, frame in enumerate(decoded):
        distances = [_color_distance(_mean_rgb(frame), expected) for expected in colors]
        assert min(range(len(distances)), key=distances.__getitem__) == index


@requires_ffmpeg
def test_positional_images_and_float_fps_still_work(tmp_path):
    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16) for i in range(2)]
    output = str(tmp_path / "legacy.mp4")

    from mcp_video.engine_images import create_from_images

    result = create_from_images(images, output, 12.0)

    assert result.output_path == output
    frames, rate = _probe_frames(output)
    assert frames == 2
    assert rate == "12/1"


@requires_ffmpeg
def test_mcp_tool_accepts_list_file_and_rational_rate(tmp_path):
    from mcp_video.server_tools_advanced import video_create_from_images

    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16) for i in range(3)]
    list_file = tmp_path / "frames.txt"
    list_file.write_text("\n".join(images) + "\n", encoding="utf-8")
    output = tmp_path / "mcp.mp4"

    result = video_create_from_images(
        list_file=str(list_file),
        output_path=str(output),
        fps="30000/1001",
    )

    assert result["success"] is True
    frames, rate = _probe_frames(str(output))
    assert frames == 3
    assert rate == "30000/1001"


def test_mcp_tool_rejects_invalid_frame_rates(tmp_path):
    from mcp_video.server_tools_advanced import video_create_from_images

    image = _write_png(tmp_path / "frame.png", 10, 10)
    for fps in (0, -1, 61, "30000/0", "abc", True):
        result = video_create_from_images(images=[image], fps=fps)
        assert result["success"] is False
        assert result["error"]["type"] == "validation_error"


@requires_ffmpeg
def test_cli_rejects_invalid_frame_rate(tmp_path):
    image = _write_png(tmp_path / "frame.png", 10, 10)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "create-from-images",
            image,
            "--fps",
            "61",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode != 0
    error = json.loads(result.stderr)["error"]
    assert error["type"] == "validation_error"


def test_cli_parser_accepts_list_file_and_rational_fps():
    from mcp_video.cli.parser import build_parser

    args = build_parser().parse_args(["create-from-images", "--list", "frames.txt", "--fps", "30000/1001"])

    assert args.inputs == []
    assert args.list_file == "frames.txt"
    assert args.fps == "30000/1001"


@requires_ffmpeg
def test_cli_positional_inputs_and_list_are_mutually_exclusive(tmp_path):
    image = _write_png(tmp_path / "frame.png", 16, 16)
    list_file = tmp_path / "frames.txt"
    list_file.write_text(image + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "create-from-images",
            image,
            "--list",
            str(list_file),
            "-o",
            str(tmp_path / "conflict.mp4"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode != 0
    error = json.loads(result.stderr)["error"]
    assert error["type"] == "validation_error"


@requires_ffmpeg
def test_cli_list_file_export_is_frame_exact(tmp_path):
    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16) for i in range(3)]
    list_file = tmp_path / "frames.txt"
    list_file.write_text("\n".join(images) + "\n", encoding="utf-8")
    output = tmp_path / "cli.mp4"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "create-from-images",
            "--list",
            str(list_file),
            "--fps",
            "24",
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["success"] is True
    frames, rate = _probe_frames(str(output))
    assert frames == 3
    assert rate == "24/1"
