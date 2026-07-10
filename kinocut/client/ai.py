"""mcp-video Python client — clean API for programmatic video editing."""

from __future__ import annotations


class ClientAiMixin:
    """Ai operations mixin."""

    def ai_remove_silence(
        self,
        video: str,
        output: str,
        silence_threshold: float = -50,
        min_silence_duration: float = 0.5,
        keep_margin: float = 0.1,
    ) -> str:
        """Remove silent sections from video."""
        from ..ai_engine import ai_remove_silence

        return ai_remove_silence(video, output, silence_threshold, min_silence_duration, keep_margin)

    def ai_transcribe(
        self, video: str, output_srt: str | None = None, model: str = "base", language: str | None = None
    ) -> dict:
        """Transcribe speech to text using Whisper.

        Args:
            video: Input video/audio path
            output_srt: If provided, write SRT subtitle file to this path
            model: Whisper model name (base, small, medium, large)
            language: Language code (e.g. "en"), or None for auto-detect

        Returns:
            dict with keys:
                - transcript (str): Full transcript text
                - segments (list[dict]): Timestamped segments
                - language (str): Detected language
        """
        from ..ai_engine import ai_transcribe

        return ai_transcribe(video, output_srt, model, language)

    def analyze_video(
        self,
        video: str,
        *,
        whisper_model: str = "base",
        language: str | None = None,
        scene_threshold: float = 0.3,
        include_transcript: bool = True,
        include_scenes: bool = True,
        include_audio: bool = True,
        include_quality: bool = True,
        include_chapters: bool = True,
        include_colors: bool = True,
        output_srt: str | None = None,
        output_txt: str | None = None,
        output_md: str | None = None,
        output_json: str | None = None,
    ) -> dict:
        """Comprehensive video analysis — transcript, metadata, scenes, audio, quality, chapters, colors.

        Points at any existing video file and reverse-engineers everything about it.

        Args:
            video: Path to existing video file.
            whisper_model: Whisper model size (tiny, base, small, medium, large, turbo).
            language: Language code for transcription (auto-detect if None).
            scene_threshold: Scene change sensitivity 0.0-1.0.
            include_transcript: Run speech-to-text via Whisper (requires openai-whisper).
            include_scenes: Detect scene changes and boundaries.
            include_audio: Analyse audio waveform, peaks, and silence regions.
            include_quality: Run visual quality check.
            include_chapters: Auto-generate chapter markers from scene changes.
            include_colors: Extract dominant colors and extended metadata.
            output_srt: Optional path to write SRT subtitle file.
            output_txt: Optional path to write plain-text transcript.
            output_md: Optional path to write Markdown transcript with timestamps.
            output_json: Optional path to write full JSON transcript data.

        Returns:
            dict with keys: success, video, metadata, transcript, scenes, audio,
            chapters, colors, quality, errors.
        """
        from ..ai_engine import analyze_video as _analyze_video

        return _analyze_video(
            video,
            whisper_model=whisper_model,
            language=language,
            scene_threshold=scene_threshold,
            include_transcript=include_transcript,
            include_scenes=include_scenes,
            include_audio=include_audio,
            include_quality=include_quality,
            include_chapters=include_chapters,
            include_colors=include_colors,
            output_srt=output_srt,
            output_txt=output_txt,
            output_md=output_md,
            output_json=output_json,
        )

    def ai_scene_detect(self, video: str, threshold: float = 0.3, use_ai: bool = False) -> list[dict]:
        """Detect scene changes in video."""
        from ..ai_engine import ai_scene_detect

        return ai_scene_detect(video, threshold, use_ai)

    def ai_stem_separation(
        self, video: str, output_dir: str, stems: list[str] | None = None, model: str = "htdemucs"
    ) -> dict[str, str]:
        """Separate audio into stems using Demucs.

        Args:
            video: Input video/audio path
            output_dir: Directory to write separated stem files
            stems: List of stems to extract (e.g. ["vocals", "drums"]). Default (None)
                extracts all four: vocals, drums, bass, other
            model: Demucs model name (htdemucs, htdemucs_ft, mdx_extra)

        Returns:
            dict mapping stem name to output WAV file path, e.g.
            {"vocals": "/path/to/vocals.wav", "drums": "/path/to/drums.wav", ...}
        """
        from ..ai_engine import ai_stem_separation

        return ai_stem_separation(video, output_dir, stems, model)

    def ai_upscale(self, video: str, output: str, scale: int = 2, model: str = "realesrgan") -> str:
        """Upscale video using AI super-resolution.

        Args:
            video: Input video path
            output: Output video path
            scale: Upscale factor (2 or 4). CLI: -s/--scale accepts {2, 4}
            model: Model name (realesrgan, bsrgan)

        Raises:
            ValueError: If scale is not 2 or 4
        """
        from ..ai_engine import ai_upscale

        return ai_upscale(video, output, scale, model)

    def ai_color_grade(self, video: str, output: str, reference: str | None = None, style: str = "auto") -> str:
        """Auto color grade video."""
        from ..ai_engine import ai_color_grade

        return ai_color_grade(video, output, reference, style)
