"""Kinocut Python client media operations."""

from __future__ import annotations

from typing import Any, ClassVar

from ..engine import (
    add_audio as _add_audio,
    add_text as _add_text,
    apply_filter as _apply_filter,
    apply_mask as _apply_mask,
    compare_quality as _compare_quality,
    composite_layers as _composite_layers,
    convert as _convert,
    create_from_images as _create_from_images,
    crop as _crop,
    detect_scenes as _detect_scenes,
    edit_timeline as _edit_timeline,
    export_frames as _export_frames,
    export_video as _export_video,
    extract_audio as _extract_audio,
    fade as _fade,
    generate_subtitles as _generate_subtitles,
    hls_segment as _hls_segment,
    luma_key as _luma_key,
    merge as _merge,
    normalize_audio as _normalize_audio,
    overlay_video as _overlay_video,
    preview as _preview,
    read_metadata as _read_metadata,
    resize as _resize,
    rotate as _rotate,
    shape_mask as _shape_mask,
    split_screen as _split_screen,
    stabilize as _stabilize,
    storyboard as _storyboard,
    subtitles as _subtitles,
    speed as _speed,
    thumbnail as _thumbnail,
    trim as _trim,
    watermark as _watermark,
    write_metadata as _write_metadata,
)
from ..errors import MCPVideoError
from ..models import (
    EditResult,
    ImageSequenceResult,
    MetadataResult,
    QualityMetricsResult,
    SceneDetectionResult,
    StoryboardResult,
    SubtitleResult,
    ThumbnailResult,
    _validate_position,
)


class ClientMediaMixin:
    """Media operations mixin."""

    def trim(
        self,
        input: str,
        start: str | float = 0,
        duration: str | float | None = None,
        end: str | float | None = None,
        output: str | None = None,
        accurate: bool = False,
    ) -> EditResult:
        """Trim a clip by start time and duration.

        Set ``accurate=True`` for frame-accurate output seeking (slower).
        """
        return _trim(input, start=start, duration=duration, end=end, output_path=output, accurate=accurate)

    def merge(
        self,
        clips: list[str],
        output: str | None = None,
        transitions: list[str] | None = None,
        transition_duration: float = 1.0,
    ) -> EditResult:
        """Merge multiple clips into one video.

        Args:
            clips: List of video file paths.
            output: Output file path.
            transitions: Transition types applied between each clip pair.
                One per boundary (len = len(clips)-1). If fewer provided,
                the last type is repeated. Example: ["fade", "dissolve", "fade"].
            transition_duration: Duration of each transition in seconds.
        """
        if not clips:
            raise MCPVideoError("clips cannot be empty", error_type="validation_error", code="empty_clips")
        return _merge(clips, output_path=output, transitions=transitions, transition_duration=transition_duration)

    def add_text(
        self,
        video: str,
        text: str,
        position: str = "top-center",
        font: str | None = None,
        size: int = 48,
        color: str = "white",
        shadow: bool = True,
        start_time: float | None = None,
        duration: float | None = None,
        output: str | None = None,
        crf: int | None = None,
        preset: str | None = None,
    ) -> EditResult:
        """Overlay text on a video."""
        if not text or not text.strip():
            raise MCPVideoError("Text cannot be empty", error_type="validation_error", code="invalid_parameter")
        return _add_text(
            video,
            text=text,
            position=position,
            font=font,
            size=size,
            color=color,
            shadow=shadow,
            start_time=start_time,
            duration=duration,
            output_path=output,
            crf=crf,
            preset=preset,
        )

    def add_audio(
        self,
        video: str,
        audio: str,
        volume: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        mix: bool = False,
        start_time: float | None = None,
        output: str | None = None,
    ) -> EditResult:
        """Add or replace audio track."""
        return _add_audio(
            video,
            audio_path=audio,
            volume=volume,
            fade_in=fade_in,
            fade_out=fade_out,
            mix=mix,
            start_time=start_time,
            output_path=output,
        )

    def resize(
        self,
        video: str,
        width: int | None = None,
        height: int | None = None,
        aspect_ratio: str | None = None,
        quality: str = "high",
        output: str | None = None,
    ) -> EditResult:
        """Resize a video or change aspect ratio."""
        if width is not None and width <= 0:
            raise MCPVideoError("width must be > 0", error_type="validation_error", code="invalid_parameter")
        if height is not None and height <= 0:
            raise MCPVideoError("height must be > 0", error_type="validation_error", code="invalid_parameter")
        return _resize(
            video,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            quality=quality,
            output_path=output,
        )

    _VALID_FORMATS: ClassVar[set[str]] = {"mp4", "webm", "gif", "mov", "hevc", "av1", "prores"}
    _VALID_QUALITIES: ClassVar[set[str]] = {"low", "medium", "high", "ultra"}
    _VALID_HLS_QUALITIES: ClassVar[set[str]] = {"low", "medium", "high", "ultra"}
    _VALID_QUALITY_METRICS: ClassVar[set[str]] = {"psnr", "ssim"}

    def convert(
        self,
        video: str,
        format: str = "mp4",
        quality: str = "high",
        output: str | None = None,
        two_pass: bool = False,
        target_bitrate: int | None = None,
    ) -> EditResult:
        """Convert video to a different format.

        Args:
            video: Input video path
            format: Output format (mp4, webm, gif, mov, hevc, av1, prores). CLI: -f/--format
            quality: Quality preset (low, medium, high, ultra). CLI: -q/--quality
            output: Output file path
            two_pass: Enable two-pass encoding
            target_bitrate: Target bitrate in kbps

        Raises:
            ValueError: If format or quality is invalid
        """
        self._validate_choice("format", format, self._VALID_FORMATS)
        self._validate_choice("quality", quality, self._VALID_QUALITIES)
        return _convert(
            video, format=format, quality=quality, output_path=output, two_pass=two_pass, target_bitrate=target_bitrate
        )

    def speed(
        self,
        video: str,
        factor: float = 1.0,
        output: str | None = None,
    ) -> EditResult:
        """Change playback speed."""
        if factor <= 0:
            raise MCPVideoError("factor must be > 0", error_type="validation_error", code="invalid_parameter")
        return _speed(video, factor=factor, output_path=output)

    def thumbnail(
        self,
        video: str,
        timestamp: float | None = None,
        output: str | None = None,
    ) -> ThumbnailResult:
        """Extract a frame from a video."""
        return _thumbnail(video, timestamp=timestamp, output_path=output)

    def extract_frame(
        self,
        video: str,
        timestamp: float | None = None,
        output: str | None = None,
    ) -> ThumbnailResult:
        """Extract a frame from a video. Alias for thumbnail()."""
        return _thumbnail(video, timestamp=timestamp, output_path=output)

    def preview(
        self,
        video: str,
        output: str | None = None,
        scale_factor: int = 4,
    ) -> EditResult:
        """Generate a fast low-res preview."""
        return _preview(video, output_path=output, scale_factor=scale_factor)

    def storyboard(
        self,
        video: str,
        output_dir: str | None = None,
        frame_count: int = 8,
    ) -> StoryboardResult:
        """Extract key frames as storyboard for human review."""
        return _storyboard(video, output_dir=output_dir, frame_count=frame_count)

    def subtitles(
        self,
        video: str,
        subtitle_file: str,
        output: str | None = None,
    ) -> EditResult:
        """Burn subtitles into a video."""
        return _subtitles(video, subtitle_path=subtitle_file, output_path=output)

    def watermark(
        self,
        video: str,
        image: str,
        position: str = "bottom-right",
        opacity: float = 0.7,
        margin: int = 20,
        output: str | None = None,
        crf: int | None = None,
        preset: str | None = None,
    ) -> EditResult:
        """Add image watermark."""
        _validate_position(position)
        return _watermark(
            video,
            image_path=image,
            position=position,
            opacity=opacity,
            margin=margin,
            output_path=output,
            crf=crf,
            preset=preset,
        )

    def crop(
        self,
        video: str,
        width: int | None = None,
        height: int | None = None,
        x: int | None = None,
        y: int | None = None,
        output: str | None = None,
        crop_percent: float | None = None,
    ) -> EditResult:
        """Crop a video to a rectangular region.

        Provide either ``width`` + ``height`` or ``crop_percent`` (e.g. 50
        for a center 50% crop).  ``x`` and ``y`` default to center.
        """
        return _crop(
            video,
            width=width,
            height=height,
            x=x,
            y=y,
            output_path=output,
            crop_percent=crop_percent,
        )

    def rotate(
        self,
        video: str,
        angle: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
        output: str | None = None,
    ) -> EditResult:
        """Rotate and/or flip a video."""
        return _rotate(
            video, angle=angle, flip_horizontal=flip_horizontal, flip_vertical=flip_vertical, output_path=output
        )

    def fade(
        self,
        video: str,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        output: str | None = None,
        crf: int | None = None,
        preset: str | None = None,
    ) -> EditResult:
        """Add fade in/out effect to a video."""
        return _fade(
            video,
            fade_in=fade_in,
            fade_out=fade_out,
            output_path=output,
            crf=crf,
            preset=preset,
        )

    def export(
        self,
        video: str,
        output: str | None = None,
        quality: str = "high",
        format: str = "mp4",
    ) -> EditResult:
        """Render final video with quality settings.

        Args:
            video: Input video path
            output: Output file path
            quality: Quality preset (low, medium, high, ultra). CLI: -q/--quality
            format: Output format (mp4, webm, gif, mov)

        Raises:
            ValueError: If quality is invalid
        """
        self._validate_choice("quality", quality, self._VALID_QUALITIES)
        self._validate_choice("format", format, self._VALID_FORMATS)
        return _export_video(video, output_path=output, quality=quality, format=format)

    def edit(self, timeline: dict[str, Any], output: str | None = None) -> EditResult:
        """Execute a full timeline-based edit from JSON."""
        return _edit_timeline(timeline, output_path=output)

    def extract_audio(
        self,
        video: str,
        output: str | None = None,
        format: str = "mp3",
    ) -> EditResult:
        """Extract audio track from video."""
        result_path = _extract_audio(video, output_path=output, format=format)
        return EditResult(
            output_path=result_path,
            operation="extract_audio",
            format=format,
        )

    def filter(
        self,
        video: str,
        filter_type: str,
        params: dict | None = None,
        output: str | None = None,
        crf: int | None = None,
        preset: str | None = None,
    ) -> EditResult:
        """Apply a visual filter to a video."""
        return _apply_filter(
            video,
            filter_type=filter_type,
            params=params,
            output_path=output,
            crf=crf,
            preset=preset,
        )

    def blur(
        self,
        video: str,
        radius: int = 5,
        strength: int = 1,
        output: str | None = None,
    ) -> EditResult:
        """Apply blur effect to a video."""
        return _apply_filter(
            video,
            filter_type="blur",
            params={"radius": radius, "strength": strength},
            output_path=output,
        )

    def reverse(
        self,
        video: str,
        output: str | None = None,
    ) -> EditResult:
        """Reverse video and audio playback."""
        from ..engine import reverse as _reverse

        return _reverse(input_path=video, output_path=output)

    def chroma_key(
        self,
        video: str,
        color: str = "0x00FF00",
        similarity: float = 0.01,
        blend: float = 0.0,
        output: str | None = None,
    ) -> EditResult:
        """Remove a solid color background (green screen / chroma key)."""
        from ..engine import chroma_key as _chroma_key

        return _chroma_key(input_path=video, color=color, similarity=similarity, blend=blend, output_path=output)

    def color_grade(
        self,
        video: str,
        preset: str = "warm",
        output: str | None = None,
    ) -> EditResult:
        """Apply a color grading preset to a video."""
        return _apply_filter(
            video,
            filter_type="color_preset",
            params={"preset": preset},
            output_path=output,
        )

    def normalize_audio(
        self,
        video: str,
        target_lufs: float = -16.0,
        output: str | None = None,
    ) -> EditResult:
        """Normalize audio loudness to a target LUFS level."""
        return _normalize_audio(video, target_lufs=target_lufs, output_path=output)

    def overlay_video(
        self,
        background: str,
        overlay: str,
        position: str = "top-right",
        width: int | None = None,
        height: int | None = None,
        opacity: float = 0.8,
        start_time: float | None = None,
        duration: float | None = None,
        output: str | None = None,
        crf: int | None = None,
        preset: str | None = None,
    ) -> EditResult:
        """Picture-in-picture: overlay a video on top of another."""
        _validate_position(position)
        return _overlay_video(
            background_path=background,
            overlay_path=overlay,
            position=position,
            width=width,
            height=height,
            opacity=opacity,
            start_time=start_time,
            duration=duration,
            output_path=output,
            crf=crf,
            preset=preset,
        )

    def split_screen(
        self,
        left: str,
        right: str,
        layout: str = "side-by-side",
        output: str | None = None,
    ) -> EditResult:
        """Place two videos side by side or top/bottom."""
        return _split_screen(left_path=left, right_path=right, layout=layout, output_path=output)

    def detect_scenes(
        self,
        video: str,
        threshold: float = 0.3,
        min_scene_duration: float = 1.0,
    ) -> SceneDetectionResult:
        """Detect scene changes in a video."""
        return _detect_scenes(video, threshold=threshold, min_scene_duration=min_scene_duration)

    def create_from_images(
        self,
        images: list[str] | None = None,
        output: str | None = None,
        fps: float = 30.0,
        *,
        output_path: str | None = None,
        **kwargs: Any,
    ) -> EditResult:
        """Create a video from a sequence of images."""
        if "inputs" in kwargs:
            raise MCPVideoError(
                "Use 'images=' not 'inputs=' — see Client.create_from_images() signature.",
                error_type="validation_error",
                code="wrong_parameter_name",
            )
        if kwargs:
            bad = next(iter(kwargs))
            raise MCPVideoError(
                f"create_from_images() got unexpected parameter '{bad}'. Use images= and output_path=.",
                error_type="validation_error",
                code="unexpected_parameter",
            )
        output = self._resolve_alias("output_path", output_path, "output", output)
        if not images:
            raise MCPVideoError("images cannot be empty", error_type="validation_error", code="empty_images")
        return _create_from_images(images, output_path=output, fps=fps)

    def export_frames(
        self,
        video: str,
        output_dir: str | None = None,
        fps: float = 1.0,
        format: str = "jpg",
    ) -> ImageSequenceResult:
        """Export frames from a video as images."""
        return _export_frames(video, output_dir=output_dir, fps=fps, format=format)

    def generate_subtitles(
        self,
        video: str,
        entries: list[dict],
        burn: bool = False,
        output: str | None = None,
    ) -> SubtitleResult:
        """Generate SRT subtitles from text entries and optionally burn into video."""
        return _generate_subtitles(entries, video, burn=burn, output_path=output)

    def compare_quality(
        self,
        original: str,
        distorted: str,
        metrics: list[str] | None = None,
    ) -> QualityMetricsResult:
        """Compare video quality between original and processed versions."""
        return _compare_quality(original, distorted, metrics=metrics)

    def repurpose_plan(
        self,
        video: str,
        output_dir: str | None = None,
        platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a dry-run repurposing manifest."""
        from ..engine_repurpose import repurpose_plan

        return repurpose_plan(video, output_dir=output_dir, platforms=platforms)

    def repurpose(
        self,
        video: str,
        output_dir: str | None = None,
        platforms: list[str] | None = None,
        include_release_checkpoint: bool = True,
        min_score: float = 0.0,
    ) -> dict[str, Any]:
        """Render a local repurposing package."""
        from ..engine_repurpose import repurpose

        return repurpose(
            video,
            output_dir=output_dir,
            platforms=platforms,
            include_release_checkpoint=include_release_checkpoint,
            min_score=min_score,
        )

    def read_metadata(
        self,
        video: str,
    ) -> MetadataResult:
        """Read metadata tags from a video/audio file."""
        return _read_metadata(video)

    def composite_layers(
        self,
        spec: str,
        output: str | None = None,
        save_layer_plan: str | None = None,
        dry_run: bool = False,
    ) -> EditResult:
        """Composite ordered image/video/solid layers from a JSON spec.

        Supports normal alpha compositing, per-layer opacity, x/y placement,
        transforms, timing windows, masks/mattes, and deterministic layer-plan
        receipts.
        """
        return _composite_layers(spec, output_path=output, save_layer_plan=save_layer_plan, dry_run=dry_run)

    def write_metadata(
        self,
        video: str,
        metadata: dict[str, str],
        output: str | None = None,
    ) -> EditResult:
        """Write metadata tags to a video/audio file."""
        return _write_metadata(video, metadata=metadata, output_path=output)

    def stabilize(
        self,
        video: str,
        smoothing: float = 15,
        zooming: float = 0,
        output: str | None = None,
    ) -> EditResult:
        """Stabilize a shaky video."""
        return _stabilize(video, smoothing=smoothing, zooming=zooming, output_path=output)

    def apply_mask(
        self,
        video: str,
        mask: str,
        feather: int = 5,
        output: str | None = None,
    ) -> EditResult:
        """Apply an image mask to a video with edge feathering."""
        return _apply_mask(video, mask_path=mask, feather=feather, output_path=output)

    def luma_key(
        self,
        video: str,
        threshold: float = 0.5,
        output: str | None = None,
    ) -> EditResult:
        """Mask out dark regions based on luminance (brightness)."""
        return _luma_key(video, threshold=threshold, output_path=output)

    def shape_mask(
        self,
        video: str,
        shape: str = "circle",
        output: str | None = None,
        feather: int = 0,
    ) -> EditResult:
        """Apply a geometric shape mask (circle, rounded_rect, oval)."""
        return _shape_mask(video, shape=shape, output_path=output, feather=feather)

    def hls_segment(
        self,
        video: str,
        output_dir: str | None = None,
        segment_duration: int = 4,
        playlist_name: str = "playlist.m3u8",
        qualities: list[str] | None = None,
    ) -> EditResult:
        """Segment a video into HLS (HTTP Live Streaming) format."""
        if segment_duration <= 0:
            raise MCPVideoError(
                f"segment_duration must be positive, got {segment_duration}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        for quality in qualities or []:
            self._validate_choice("qualities", quality, self._VALID_HLS_QUALITIES)
        return _hls_segment(
            video,
            output_dir=output_dir,
            segment_duration=segment_duration,
            playlist_name=playlist_name,
            qualities=qualities,
        )

    def batch(
        self,
        inputs: list[str],
        operation: str,
        params: dict | None = None,
        output_dir: str | None = None,
    ) -> dict:
        """Apply the same operation to multiple video files."""
        from ..engine import video_batch

        return video_batch(inputs, operation=operation, params=params, output_dir=output_dir)

    # ------------------------------------------------------------------
    # Image Analysis
    # ------------------------------------------------------------------
