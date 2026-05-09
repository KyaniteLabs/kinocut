"""Tests for Pydantic models — no FFmpeg needed."""

import pytest

from mcp_video.models import (
    ASPECT_RATIOS,
    PREVIEW_PRESETS,
    QUALITY_PRESETS,
    EditResult,
    ErrorResult,
    StoryboardResult,
    ThumbnailResult,
    Timeline,
    TimelineClip,
    TimelineExport,
    TimelineTextElement,
    TimelineTrack,
    TimelineTransition,
    VideoInfo,
    WatermarkSettings,
    _position_coords,
    _resolve_position,
)


class TestVideoInfo:
    def test_creation_and_properties(self):
        info = VideoInfo(
            path="/tmp/video.mp4",
            duration=10.5,
            width=1920,
            height=1080,
            fps=30.0,
            codec="h264",
            audio_codec="aac",
            audio_sample_rate=44100,
            bitrate=5000000,
            size_bytes=10485760,
            format="mp4",
        )
        assert info.path == "/tmp/video.mp4"
        assert info.duration == 10.5
        assert info.resolution == "1920x1080"
        assert info.aspect_ratio == "16:9"
        assert info.size_mb == 10.0
        assert info.model_dump()["path"] == "/tmp/video.mp4"

    @pytest.mark.parametrize(
        "width,height,expected_ratio",
        [
            (1920, 1080, "16:9"),
            (640, 480, "4:3"),
            (1080, 1920, "9:16"),
            (100, 100, "1:1"),
        ],
    )
    def test_aspect_ratios(self, width, height, expected_ratio):
        info = VideoInfo(path="/tmp/v.mp4", duration=1.0, width=width, height=height, fps=30.0, codec="h264")
        assert info.aspect_ratio == expected_ratio

    def test_optional_defaults(self):
        info = VideoInfo(path="/tmp/v.mp4", duration=5.0, width=640, height=480, fps=24.0, codec="h264")
        assert info.audio_codec is None
        assert info.size_mb is None

    def test_size_mb_rounding(self):
        info = VideoInfo(
            path="/tmp/v.mp4",
            duration=1.0,
            width=100,
            height=100,
            fps=30.0,
            codec="h264",
            size_bytes=1500000,
        )
        assert info.size_mb == 1.43


class TestResults:
    def test_edit_result(self):
        r = EditResult(
            output_path="/tmp/out.mp4",
            duration=10.0,
            resolution="1920x1080",
            size_mb=5.5,
            format="mp4",
            operation="trim",
            progress=50.0,
            thumbnail_base64="abc123",
        )
        assert r.success is True
        assert r.progress == 50.0
        assert r.thumbnail_base64 == "abc123"
        d = r.model_dump()
        assert d["progress"] == 50.0
        assert "thumbnail_base64" in d

    def test_edit_result_defaults(self):
        r = EditResult(output_path="/tmp/out.mp4")
        assert r.success is True
        assert r.progress is None
        assert r.thumbnail_base64 is None

    def test_error_result(self):
        r = ErrorResult(error={"type": "test", "message": "oops"})
        assert r.success is False
        assert r.model_dump()["success"] is False

    def test_storyboard_result(self):
        r = StoryboardResult(frames=["f1.jpg", "f2.jpg"], count=2, grid="grid.jpg")
        assert r.success is True
        assert r.grid == "grid.jpg"

    def test_thumbnail_result(self):
        r = ThumbnailResult(frame_path="/tmp/f.jpg", timestamp=1.5)
        assert r.success is True
        assert r.timestamp == 1.5


class TestTimelineModels:
    def test_timeline_clip(self):
        clip = TimelineClip(source="/tmp/v.mp4")
        assert clip.source == "/tmp/v.mp4"
        assert clip.start == 0.0
        assert clip.volume == 1.0

        full = TimelineClip(
            source="/tmp/v.mp4",
            start=5.0,
            duration=10.0,
            trim_start=2.0,
            trim_end=8.0,
            volume=0.8,
        )
        assert full.trim_start == 2.0

    def test_timeline_transition(self):
        t = TimelineTransition(after_clip=0)
        assert t.type == "fade"
        assert t.duration == 1.0

        custom = TimelineTransition(after_clip=1, type="dissolve", duration=2.0)
        assert custom.type == "dissolve"

    def test_timeline_text_element(self):
        elem = TimelineTextElement(text="Hello")
        assert elem.position == "top-center"
        assert elem.style["size"] == 48

        custom = TimelineTextElement(text="Title", position="bottom-center", style={"size": 36})
        assert custom.position == "bottom-center"

    def test_timeline_track(self):
        vt = TimelineTrack(type="video")
        assert vt.clips == []
        at = TimelineTrack(type="audio", clips=[TimelineClip(source="a.mp3")])
        assert len(at.clips) == 1

        with pytest.raises(Exception):
            TimelineTrack(type="invalid")

    def test_timeline_export(self):
        exp = TimelineExport()
        assert exp.format == "mp4"
        assert exp.quality == "high"

        custom = TimelineExport(format="webm", quality="low")
        assert custom.format == "webm"

    def test_timeline(self):
        tl = Timeline()
        assert tl.width == 1920
        assert tl.tracks == []

        with_tracks = Timeline(
            width=1080,
            height=1920,
            tracks=[TimelineTrack(type="video", clips=[TimelineClip(source="v.mp4")])],
        )
        assert with_tracks.width == 1080
        assert len(with_tracks.tracks) == 1


class TestWatermarkSettings:
    def test_defaults_and_custom(self):
        wm = WatermarkSettings(image_path="/tmp/logo.png")
        assert wm.position == "bottom-right"
        assert wm.opacity == 0.7

        custom = WatermarkSettings(image_path="/tmp/logo.png", position="top-left", opacity=0.5)
        assert custom.position == "top-left"
        assert custom.opacity == 0.5


class TestPresetConstants:
    def test_quality_presets(self):
        for _level, preset in QUALITY_PRESETS.items():
            assert "crf" in preset
            assert "preset" in preset
            assert "max_height" in preset
            assert isinstance(preset["crf"], int)
            assert isinstance(preset["max_height"], int)

        crfs = [QUALITY_PRESETS[k]["crf"] for k in ["low", "medium", "high", "ultra"]]
        assert crfs == sorted(crfs, reverse=True)

    def test_aspect_ratios(self):
        assert len(ASPECT_RATIOS) == 6
        for _name, (w, h) in ASPECT_RATIOS.items():
            assert isinstance(w, int) and w > 0
            assert isinstance(h, int) and h > 0
        assert ASPECT_RATIOS["1:1"][0] == ASPECT_RATIOS["1:1"][1]

    def test_preview_presets(self):
        assert "crf" in PREVIEW_PRESETS
        assert PREVIEW_PRESETS["preset"] == "ultrafast"
        assert PREVIEW_PRESETS["scale_factor"] >= 2


class TestValidation:
    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (TimelineExport, {"format": "invalid"}),
            (TimelineExport, {"quality": "invalid"}),
            (TimelineTextElement, {"text": "Hi", "position": "invalid"}),
            (TimelineTransition, {"after_clip": 0, "type": "invalid"}),
        ],
    )
    def test_invalid_enum_rejected(self, cls, kwargs):
        with pytest.raises(Exception):
            cls(**kwargs)

    def test_position_helpers_reject_unknown_named_position(self):
        position_map = {"center": "center", "bottom-right": "bottom-right"}

        with pytest.raises(Exception, match="position must be one of"):
            _position_coords("middle-ish")

        with pytest.raises(Exception, match="position must be one of"):
            _resolve_position("middle-ish", position_map, "bottom-right")
