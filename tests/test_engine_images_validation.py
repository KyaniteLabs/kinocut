"""Published 1.16.2 image-sequence regression coverage."""

from __future__ import annotations
import os
import shutil
from pathlib import Path
import pytest
from mcp_video.errors import MCPVideoError
from mcp_video.models import EditResult
from tests.image_sequence_fixtures import (
    _write_png,
    _probe_frames,
    _decode_rgb_frames,
    _mean_rgb,
    _color_distance,
    _unstaged_output,
    SEQUENCE_COLORS,
    requires_ffmpeg,
)

pytestmark = pytest.mark.usefixtures("full_tool_surface")


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

    link = os.link

    def failing_link(src, dst, **kwargs):
        if ".kinocut_tmp_" in str(src):
            return link(src, dst, **kwargs)
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
        link = os.link

        def failing_link(src, dst, **kwargs):
            if ".kinocut_tmp_" in str(src):
                return link(src, dst, **kwargs)
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
