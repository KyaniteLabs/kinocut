"""Frame-exact image-sequence export tests for :mod:`mcp_video.engine_images`.

The exactness assertions use real FFmpeg/ffprobe; the validation and
normalization tests are hermetic and only need the generated PNG fixtures.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.models import EditResult

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/ffprobe not installed",
)

EXACT_RATES = [
    (24, "24/1"),
    (25, "25/1"),
    (30, "30/1"),
    (60, "60/1"),
    ("30000/1001", "30000/1001"),
]


def _write_png(path, width: int, height: int, rgb: tuple[int, int, int] = (0, 0, 0)) -> str:
    """Write a minimal RGB PNG fixture without optional image dependencies."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(payload)
    return str(path)


def _probe_frames(path: str) -> tuple[int, str]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["nb_read_frames"]), stream["r_frame_rate"]


def _frame_hashes(path: str) -> list[str]:
    """Return one decoded frame hash per output frame via framemd5."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    rows = [line for line in result.stdout.splitlines() if line and not line.startswith("#")]
    return [row.split(",")[-1].strip() for row in rows]


def _decode_rgb_frames(path: str, width: int, height: int) -> list[bytes]:
    """Decode every output frame to raw RGB for lossless frame inspection."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=120,
    )
    frame_size = width * height * 3
    assert len(result.stdout) % frame_size == 0
    return [result.stdout[offset : offset + frame_size] for offset in range(0, len(result.stdout), frame_size)]


def _mean_rgb(frame: bytes) -> tuple[float, float, float]:
    pixels = len(frame) // 3
    return tuple(sum(frame[channel::3]) / pixels for channel in range(3))  # type: ignore[return-value]


def _color_distance(left: tuple[float, float, float], right: tuple[int, int, int]) -> float:
    return sum((left[channel] - right[channel]) ** 2 for channel in range(3))


@contextlib.contextmanager
def _unstaged_output(path):
    """Stand-in for atomic publication when FFmpeg itself is stubbed out."""
    yield path


SEQUENCE_COLORS: list[tuple[int, int, int]] = [
    (0, 0, 0),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
    (160, 80, 32),
    (32, 80, 160),
]


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
    from mcp_video.engine_images import _format_fps_for_ffmpeg

    assert _format_fps_for_ffmpeg("30000/1001") == "30000/1001"
    assert _format_fps_for_ffmpeg("60/1") == "60/1"
    assert _format_fps_for_ffmpeg(30) == "30"
    assert _format_fps_for_ffmpeg(29.97002997) == "29.97002997"


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


# ---------------------------------------------------------------------------
# PR #615 review: boundary validation, list bounds and fast-path link safety
# ---------------------------------------------------------------------------


def _stub_encode(monkeypatch, engine_images, calls):
    """Replace FFmpeg and result probing so the fast-path choice is observable."""

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


def _forbid_engine(monkeypatch):
    from mcp_video import server_tools_advanced

    def engine_called(*args, **kwargs):
        raise AssertionError("engine must not run when boundary validation fails")

    monkeypatch.setattr(server_tools_advanced, "create_from_images", engine_called)


@pytest.mark.parametrize("fps", [0, -1, 61, 120.5, "61/1", "121/2", "30000/0", "abc", "", True, False])
def test_mcp_tool_rejects_out_of_range_fps_before_the_engine(tmp_path, monkeypatch, fps):
    from mcp_video.server_tools_advanced import video_create_from_images

    image = _write_png(tmp_path / "frame.png", 10, 10)
    _forbid_engine(monkeypatch)

    result = video_create_from_images(images=[image], fps=fps)

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"


@pytest.mark.parametrize("fps", [1, 30, 60, 29.97, "30000/1001", "60/1", "120/2"])
def test_mcp_tool_boundary_accepts_supported_fps(tmp_path, monkeypatch, fps):
    from mcp_video import server_tools_advanced

    image = _write_png(tmp_path / "frame.png", 10, 10)
    seen = {}

    def fake_engine(images, output_path=None, fps=None, list_file=None):
        seen["fps"] = fps
        return EditResult(output_path=str(tmp_path / "out.mp4"), operation="create_from_images")

    monkeypatch.setattr(server_tools_advanced, "create_from_images", fake_engine)

    result = server_tools_advanced.video_create_from_images(images=[image], fps=fps)

    assert result["success"] is True
    assert seen["fps"] == fps


def test_mcp_tool_validates_list_file_before_the_engine(tmp_path, monkeypatch):
    from mcp_video.server_tools_advanced import video_create_from_images

    _forbid_engine(monkeypatch)

    missing = video_create_from_images(list_file=str(tmp_path / "missing.txt"))
    null_byte = video_create_from_images(list_file=str(tmp_path / "frames\x00.txt"))

    for result in (missing, null_byte):
        assert result["success"] is False
        assert result["error"]["type"] == "input_error"


def test_mcp_tool_rejects_too_many_images_before_the_engine(tmp_path, monkeypatch):
    from mcp_video import server_tools_advanced

    image = _write_png(tmp_path / "frame.png", 10, 10)
    monkeypatch.setattr(server_tools_advanced, "MAX_IMAGE_SEQUENCE_FRAMES", 2)
    _forbid_engine(monkeypatch)

    result = server_tools_advanced.video_create_from_images(images=[image] * 3)

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    assert result["error"]["code"] == "too_many_images"


def test_list_file_over_line_limit_is_rejected_before_any_image_is_checked(tmp_path, monkeypatch):
    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_FRAMES", 3)
    # The entries do not exist: the line bound must trip before any of them is validated.
    list_file = tmp_path / "frames.txt"
    list_file.write_text("\n".join(str(tmp_path / f"missing_{i}.png") for i in range(4)) + "\n", encoding="utf-8")

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images.create_from_images(list_file=str(list_file), output_path=str(tmp_path / "out.mp4"))

    assert exc_info.value.error_type == "validation_error"
    assert exc_info.value.code == "too_many_images"


def test_list_file_reading_stops_at_the_line_limit(tmp_path, monkeypatch):
    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_FRAMES", 2)
    list_file = tmp_path / "frames.txt"
    list_file.write_text("a.png\nb.png\nc.png\n" + "x" * 64 + "\n" * 1000, encoding="utf-8")

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images._read_list_file(str(list_file))

    assert exc_info.value.code == "too_many_images"


def test_list_file_at_the_line_limit_is_accepted(tmp_path, monkeypatch):
    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_FRAMES", 3)
    list_file = tmp_path / "frames.txt"
    list_file.write_text("a.png\n\nb.png\nc.png\n\n", encoding="utf-8")

    assert engine_images._read_list_file(str(list_file)) == ["a.png", "b.png", "c.png"]


def test_oversized_list_file_is_rejected_before_reading(tmp_path, monkeypatch):
    import builtins

    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_LIST_BYTES", 16)
    list_file = tmp_path / "frames.txt"
    list_file.write_text("a.png\n" * 4, encoding="utf-8")
    real_open = builtins.open

    def guarded_open(path, *args, **kwargs):
        if str(path) == os.path.realpath(list_file):
            raise AssertionError("an oversized list file must not be opened")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images._read_list_file(str(list_file))

    assert exc_info.value.code == "list_file_too_large"


def test_positional_images_over_the_limit_are_rejected(tmp_path, monkeypatch):
    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_FRAMES", 2)
    image = _write_png(tmp_path / "frame.png", 10, 10)

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images.create_from_images([image] * 3, output_path=str(tmp_path / "out.mp4"))

    assert exc_info.value.code == "too_many_images"


def test_image_sequence_limits_cover_long_exports():
    from mcp_video.limits import MAX_IMAGE_SEQUENCE_FRAMES, MAX_IMAGE_SEQUENCE_LIST_BYTES

    # Ten minutes at 30 fps must fit, and the byte bound must allow long absolute paths.
    assert MAX_IMAGE_SEQUENCE_FRAMES >= 18_000
    assert MAX_IMAGE_SEQUENCE_LIST_BYTES >= MAX_IMAGE_SEQUENCE_FRAMES * 512


def test_symlinked_png_falls_back_to_the_normalizer(tmp_path, monkeypatch):
    from mcp_video import engine_images

    real = _write_png(tmp_path / "real.png", 10, 10)
    link = tmp_path / "link.png"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    calls = {"normalize": 0}
    _stub_encode(monkeypatch, engine_images, calls)
    # _validate_input_path resolves links; keep the link name so the fast path
    # itself is shown to refuse a symlink at link time.
    monkeypatch.setattr(engine_images, "_validate_input_path", lambda path: str(path))

    engine_images.create_from_images([str(link)], output_path=str(tmp_path / "out.mp4"), fps=30)

    assert calls["normalize"] == 1


def test_fast_path_checks_the_linked_bytes_not_the_original_path(tmp_path, monkeypatch):
    """An input swapped after the header check must not enter the fast path."""
    from mcp_video import engine_images

    image = _write_png(tmp_path / "frame.png", 10, 10)
    odd = _write_png(tmp_path / "odd.png", 11, 11)
    real_link = os.link
    calls = {"normalize": 0}
    _stub_encode(monkeypatch, engine_images, calls)

    def swapping_link(src, dst, *args, **kwargs):
        # Simulate a concurrent writer replacing the input just before it is linked.
        os.replace(shutil.copy(odd, str(tmp_path / "swap.png")), src)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(engine_images.os, "link", swapping_link)

    engine_images.create_from_images([image], output_path=str(tmp_path / "out.mp4"), fps=30)

    assert calls["normalize"] == 1


def test_link_failure_falls_back_to_the_normalizer_not_a_copy(tmp_path, monkeypatch):
    from mcp_video import engine_images

    image = _write_png(tmp_path / "frame.png", 10, 10)
    calls = {"normalize": 0}
    _stub_encode(monkeypatch, engine_images, calls)

    def failing_link(*args, **kwargs):
        raise OSError("cross-device link")

    def forbidden_copy(*args, **kwargs):
        raise AssertionError("the fast path must not copy inputs")

    monkeypatch.setattr(engine_images.os, "link", failing_link)
    monkeypatch.setattr(engine_images.shutil, "copy2", forbidden_copy)
    monkeypatch.setattr(engine_images.shutil, "copyfile", forbidden_copy)

    engine_images.create_from_images([image], output_path=str(tmp_path / "out.mp4"), fps=30)

    assert calls["normalize"] == 1


@requires_ffmpeg
def test_link_failure_fallback_is_still_frame_exact_and_ordered(tmp_path, monkeypatch):
    from mcp_video import engine_images

    def failing_link(*args, **kwargs):
        raise OSError("cross-device link")

    monkeypatch.setattr(engine_images.os, "link", failing_link)
    colors = SEQUENCE_COLORS[:4]
    images = [_write_png(tmp_path / f"even_{i}.png", 16, 16, rgb=color) for i, color in enumerate(colors)]
    output = str(tmp_path / "fallback.mp4")

    engine_images.create_from_images(images, output_path=output, fps=30)

    frames, rate = _probe_frames(output)
    assert (frames, rate) == (4, "30/1")
    observed = [_mean_rgb(frame) for frame in _decode_rgb_frames(output, 16, 16)]
    for index, actual in enumerate(observed):
        distances = [_color_distance(actual, expected) for expected in colors]
        assert min(range(len(distances)), key=distances.__getitem__) == index


@requires_ffmpeg
def test_partial_fast_path_never_writes_through_a_link_to_an_input(tmp_path):
    """Even PNGs linked before an odd one is found must keep their original bytes."""
    from mcp_video.engine_images import create_from_images

    colors = SEQUENCE_COLORS[:3]
    images = [
        _write_png(tmp_path / "even_0.png", 16, 16, rgb=colors[0]),
        _write_png(tmp_path / "even_1.png", 16, 16, rgb=colors[1]),
        _write_png(tmp_path / "odd_2.png", 15, 15, rgb=colors[2]),
    ]
    before = [Path(path).read_bytes() for path in images]
    output = str(tmp_path / "mixed.mp4")

    create_from_images(images, output_path=output, fps=25)

    assert [Path(path).read_bytes() for path in images] == before
    assert _probe_frames(output) == (3, "25/1")


def test_mcp_tool_checks_the_image_count_before_validating_paths(tmp_path, monkeypatch):
    from mcp_video import server_tools_advanced

    monkeypatch.setattr(server_tools_advanced, "MAX_IMAGE_SEQUENCE_FRAMES", 2)
    _forbid_engine(monkeypatch)
    missing = [str(tmp_path / f"missing_{i}.png") for i in range(3)]

    result = server_tools_advanced.video_create_from_images(images=missing)

    # A path error here would mean every path was validated before the cheap count bound.
    assert result["error"]["code"] == "too_many_images"


@pytest.mark.parametrize(
    "fps",
    ["1" + "0" * 5000 + "/1", "30/" + "1" * 5000, "\u0663\u0660/\u0661"],
    ids=["numerator-5001-digits", "denominator-5000-digits", "arabic-indic-digits"],
)
def test_oversized_or_non_ascii_rational_fps_is_a_validation_error(tmp_path, monkeypatch, fps):
    from mcp_video import engine_images
    from mcp_video.server_tools_advanced import video_create_from_images

    image = _write_png(tmp_path / "frame.png", 10, 10)
    _forbid_engine(monkeypatch)

    result = video_create_from_images(images=[image], fps=fps)
    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    with pytest.raises(MCPVideoError) as exc_info:
        engine_images._coerce_fps(fps)
    assert exc_info.value.error_type == "validation_error"


def test_list_file_read_is_bounded_even_if_it_grows_after_the_size_check(tmp_path, monkeypatch):
    from mcp_video import engine_images

    monkeypatch.setattr(engine_images, "MAX_IMAGE_SEQUENCE_LIST_BYTES", 16)
    list_file = tmp_path / "frames.txt"
    list_file.write_text("a.png\n" * 8, encoding="utf-8")
    # Report a small size, as if the file grew between the size check and the read.
    monkeypatch.setattr(engine_images.os.path, "getsize", lambda path: 6)

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images._read_list_file(str(list_file))

    assert exc_info.value.code == "list_file_too_large"


def test_list_file_keeps_universal_newline_handling(tmp_path):
    from mcp_video import engine_images

    list_file = tmp_path / "frames.txt"
    list_file.write_bytes("\ufeffa.png\r\nb.png\rc.png\n\n  d.png  \n".encode())

    assert engine_images._read_list_file(str(list_file)) == ["a.png", "b.png", "c.png", "d.png"]


def test_sequence_pattern_escapes_percent_in_the_directory():
    from mcp_video.engine_images import _sequence_pattern

    pattern = _sequence_pattern("tmp%d_dir", ".png")

    assert pattern.startswith("tmp%%d_dir")
    assert pattern.endswith("frame_%08d.png")


@requires_ffmpeg
@pytest.mark.parametrize("force_normalizer", [False, True])
def test_percent_in_the_temp_directory_still_encodes_exactly(tmp_path, monkeypatch, force_normalizer):
    import tempfile

    from mcp_video import engine_images

    temp_root = tmp_path / "tmp%dpct"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    if force_normalizer:

        def failing_link(*args, **kwargs):
            raise OSError("cross-device link")

        monkeypatch.setattr(engine_images.os, "link", failing_link)
    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16, rgb=SEQUENCE_COLORS[i]) for i in range(3)]
    output = str(tmp_path / "percent.mp4")

    engine_images.create_from_images(images, output_path=output, fps=30)

    assert _probe_frames(output) == (3, "30/1")
    observed = [_mean_rgb(frame) for frame in _decode_rgb_frames(output, 16, 16)]
    for index, actual in enumerate(observed):
        distances = [_color_distance(actual, expected) for expected in SEQUENCE_COLORS[:3]]
        assert min(range(len(distances)), key=distances.__getitem__) == index


# ---------------------------------------------------------------------------
# PR #616 review: corrupt inputs must fail; booleans rejected at MCP admission
# ---------------------------------------------------------------------------


def _truncate_to_header(path: str) -> None:
    """Keep only the PNG signature and IHDR dimensions, as a corrupt file would."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    with open(path, "wb") as handle:
        handle.write(header)


@requires_ffmpeg
@pytest.mark.parametrize("force_normalizer", [False, True], ids=["fast-path", "normalizer"])
def test_corrupt_middle_png_fails_instead_of_dropping_a_frame(tmp_path, monkeypatch, force_normalizer):
    from mcp_video import engine_images

    if force_normalizer:

        def failing_link(*args, **kwargs):
            raise OSError("cross-device link")

        monkeypatch.setattr(engine_images.os, "link", failing_link)
    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16, rgb=SEQUENCE_COLORS[i]) for i in range(3)]
    _truncate_to_header(images[1])
    output = tmp_path / "corrupt.mp4"

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images.create_from_images(images, output_path=str(output), fps=30)

    assert exc_info.value.error_type in {"processing_error", "input_error"}
    assert not output.exists(), "an incomplete export must not be left behind as a success"


@requires_ffmpeg
def test_output_frame_count_is_verified_before_success(tmp_path, monkeypatch):
    """Even if FFmpeg exits 0, a short output must not be reported as success."""
    from mcp_video import engine_images

    images = [_write_png(tmp_path / f"frame_{i}.png", 16, 16, rgb=SEQUENCE_COLORS[i]) for i in range(3)]
    real_run = engine_images._run_ffmpeg

    def drop_last_frame(args):
        # Simulate an encoder that silently stops early: ask for one frame fewer.
        args = list(args)
        if "-frames:v" in args and "-update" not in args:
            index = args.index("-frames:v") + 1
            args[index] = str(int(args[index]) - 1)
        return real_run(args)

    monkeypatch.setattr(engine_images, "_run_ffmpeg", drop_last_frame)
    output = tmp_path / "short.mp4"

    with pytest.raises(MCPVideoError) as exc_info:
        engine_images.create_from_images(images, output_path=str(output), fps=30)

    assert exc_info.value.code == "frame_count_mismatch"
    assert not output.exists()


def _mcp_call(name, arguments):
    import asyncio

    from kinocut.server import mcp

    return asyncio.run(mcp.call_tool(name, arguments))


@pytest.mark.parametrize("fps", [True, False])
def test_actual_mcp_call_rejects_boolean_fps_before_the_engine(tmp_path, monkeypatch, fps):
    image = _write_png(tmp_path / "frame.png", 10, 10)
    _forbid_engine(monkeypatch)

    result = _mcp_call("video_create_from_images", {"images": [image], "fps": fps})

    assert result.isError is True
    assert result.structuredContent["success"] is False
    assert result.structuredContent["error"]["type"] == "validation_error"


@pytest.mark.parametrize("fps", [30, 29.97, "30000/1001", "60/1"])
def test_actual_mcp_call_accepts_numeric_and_rational_fps(tmp_path, monkeypatch, fps):
    from mcp_video import server_tools_advanced

    image = _write_png(tmp_path / "frame.png", 10, 10)
    seen = {}

    def fake_engine(images, output_path=None, fps=None, list_file=None):
        seen["fps"] = fps
        return EditResult(output_path=str(tmp_path / "out.mp4"), operation="create_from_images")

    monkeypatch.setattr(server_tools_advanced, "create_from_images", fake_engine)

    result = _mcp_call("video_create_from_images", {"images": [image], "fps": fps})

    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload["success"] is True
    assert seen["fps"] == fps
    assert type(seen["fps"]) is type(fps)
