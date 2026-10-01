"""A failed core edit must preserve a previously delivered media file."""

from pathlib import Path
import importlib

import pytest

from kinocut.errors import ProcessingError
from kinocut.ffmpeg_helpers import _reset_operation_inputs


CASES = [
    ("engine_crop", "crop", {"width": 100, "height": 100}),
    ("engine_rotate", "rotate", {"angle": 90}),
    ("engine_watermark", "watermark", {"image_path": "image"}),
    ("engine_fade", "fade", {"fade_in": 0.2}),
    ("engine_reverse", "reverse", {}),
    ("engine_preview", "preview", {}),
    ("engine_overlay", "overlay_video", {"overlay_path": "video", "width": 100}),
    ("engine_split_screen", "split_screen", {"right_path": "video"}),
    ("engine_mask", "apply_mask", {"mask_path": "image"}),
    ("engine_transcode", "normalize", {}),
    ("engine_filters", "apply_filter", {"filter_type": "brightness"}),
    ("engine_text", "add_text", {"text": "Delivered caption"}),
    ("engine_subtitles", "subtitles", {"subtitle_path": "subtitle"}),
    ("engine_stabilize", "stabilize", {}),
    ("engine_merge", "merge", {}),
]


@pytest.fixture(autouse=True)
def isolated_operation():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


@pytest.mark.parametrize("module_name,function_name,parameters", CASES, ids=[case[1] for case in CASES])
def test_partial_encoder_failure_preserves_delivery(
    module_name,
    function_name,
    parameters,
    tmp_path,
    sample_video,
    sample_video_2,
    sample_watermark_png,
    sample_srt,
    monkeypatch,
):
    module = importlib.import_module(f"kinocut.{module_name}")
    params = {
        key: {"video": sample_video_2, "image": sample_watermark_png, "subtitle": sample_srt}.get(value, value)
        for key, value in parameters.items()
    }
    output = tmp_path / "delivered.mp4"
    original = Path(sample_video).read_bytes()
    output.write_bytes(original)

    def partial_failed_render(cmd):
        Path(cmd[-1]).write_bytes(b"interrupted encoder output")
        raise ProcessingError("ffmpeg", 1, "Simulated disk exhaustion after partial output")

    monkeypatch.setattr(module, "_run_ffmpeg", partial_failed_render)
    if module_name == "engine_stabilize":
        monkeypatch.setattr(module, "_require_filter", lambda *args: None)
        monkeypatch.setattr(module, "_detect_motion_vectors", lambda *args: None)
    source = [sample_video, sample_video] if function_name == "merge" else sample_video
    with pytest.raises(ProcessingError):
        getattr(module, function_name)(source, output_path=str(output), **params)
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("position", ["top-center", "center-left", "bottom-center"])
def test_watermark_centered_named_positions_render(position, tmp_path, sample_video, sample_watermark_png):
    from kinocut.engine_watermark import watermark
    from kinocut.engine_probe import probe

    output = str(tmp_path / f"{position}.mp4")
    result = watermark(sample_video, sample_watermark_png, position=position, margin=12, output_path=output)
    assert result.output_path == output
    assert probe(output).duration > 0


@pytest.mark.parametrize("margin", ["0;movie=private", "0:0", True, -1, 1.5, float("inf")])
def test_watermark_rejects_untrusted_margin_before_render(margin, sample_video, sample_watermark_png, monkeypatch):
    from kinocut import engine_watermark
    from kinocut.errors import MCPVideoError

    def unexpected_render(*args, **kwargs):
        pytest.fail("Untrusted margin reached FFmpeg")

    monkeypatch.setattr(engine_watermark, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_watermark.watermark(sample_video, sample_watermark_png, margin=margin)
    assert exc.value.error_type == "validation_error"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 10**1000])
def test_shared_normalized_validation_rejects_nonfinite_or_overflow(value):
    from kinocut.validation import _validate_normalized_float
    from kinocut.errors import MCPVideoError

    with pytest.raises(MCPVideoError) as exc:
        _validate_normalized_float(value, "opacity")
    assert exc.value.error_type == "validation_error"


def test_shared_filter_number_overflow_is_structured():
    from kinocut.ffmpeg_helpers import _sanitize_ffmpeg_number
    from kinocut.errors import MCPVideoError

    with pytest.raises(MCPVideoError) as exc:
        _sanitize_ffmpeg_number(10**1000, "factor")
    assert exc.value.error_type == "validation_error"


@pytest.mark.parametrize("factor", ["bad", float("nan"), float("inf"), True, 1.5, 0])
def test_preview_invalid_scale_has_structured_validation(factor, sample_video, monkeypatch):
    from kinocut import engine_preview
    from kinocut.errors import MCPVideoError

    def unexpected_render(*args, **kwargs):
        pytest.fail("Invalid preview scale reached FFmpeg")

    monkeypatch.setattr(engine_preview, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_preview.preview(sample_video, scale_factor=factor)
    assert exc.value.error_type == "validation_error"


@pytest.mark.parametrize("factor", [0.000001, 101, 10**1000, float("nan"), True])
def test_engine_speed_enforces_shared_public_resource_bounds(factor, sample_video, monkeypatch):
    from kinocut import engine_speed
    from kinocut.errors import MCPVideoError

    def unexpected_render(*args, **kwargs):
        pytest.fail("Unsupported speed reached FFmpeg")

    monkeypatch.setattr(engine_speed, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_speed.speed(sample_video, factor=factor)
    assert exc.value.error_type == "validation_error"


def test_engine_speed_rejects_excessive_output_duration_before_render(sample_video, monkeypatch):
    from types import SimpleNamespace
    from kinocut import engine_speed
    from kinocut.errors import MCPVideoError
    from kinocut.limits import MAX_VIDEO_DURATION, MIN_SPEED_FACTOR

    monkeypatch.setattr(engine_speed, "probe", lambda _: SimpleNamespace(duration=MAX_VIDEO_DURATION))
    with pytest.raises(MCPVideoError) as exc:
        engine_speed.speed(sample_video, factor=MIN_SPEED_FACTOR)
    assert exc.value.code == "duration_too_long"


@pytest.mark.parametrize(
    "parameters",
    [
        {"width": "bad", "height": 100},
        {"width": True, "height": 100},
        {"width": 100, "height": 1.5},
        {"width": 100, "height": 100, "x": -1},
        {"width": 100, "height": 100, "x": 600},
        {"crop_percent": float("nan")},
    ],
)
def test_crop_invalid_rectangle_is_rejected_before_render(parameters, sample_video, monkeypatch):
    from kinocut import engine_crop
    from kinocut.errors import MCPVideoError

    def unexpected_render(*args, **kwargs):
        pytest.fail("Invalid crop reached FFmpeg")

    monkeypatch.setattr(engine_crop, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_crop.crop(sample_video, **parameters)
    assert exc.value.error_type == "validation_error"


def test_split_screen_unknown_layout_is_rejected(sample_video, monkeypatch):
    from kinocut import engine_split_screen
    from kinocut.errors import MCPVideoError

    def unexpected_render(*args, **kwargs):
        pytest.fail("Unknown layout reached FFmpeg")

    monkeypatch.setattr(engine_split_screen, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_split_screen.split_screen(sample_video, sample_video, layout="diagonal")
    assert exc.value.code == "invalid_layout"
