"""Kinocut Python client audio operations."""

from __future__ import annotations

from typing import Any, Literal

from ..defaults import (
    DEFAULT_AUDIO_MIX_BITRATE,
    DEFAULT_DUCK_ATTACK_MS,
    DEFAULT_DUCK_MUSIC_VOLUME,
    DEFAULT_DUCK_RATIO,
    DEFAULT_DUCK_RELEASE_MS,
    DEFAULT_DUCK_THRESHOLD,
)
from ..engine import (
    audio_waveform as _audio_waveform,
)
from ..errors import MCPVideoError
from ..models import (
    EditResult,
    WaveformResult,
)


class ClientAudioMixin:
    """Audio operations mixin."""

    def mix_audio(
        self,
        video: str,
        tracks: list[dict],
        output: str | None = None,
        keep_source: bool = True,
        *,
        audio_bitrate: str = DEFAULT_AUDIO_MIX_BITRATE,
    ) -> EditResult:
        """Mix timed tracks once, stream-copying picture and preserving video duration.

        Each track accepts path, start, volume, fade_in and fade_out. Gains sum
        without normalization and may clip; listen before publishing. Fades apply
        to the audible segment, clipped at the video's end. No project store is
        needed. This API encodes AAC once instead of repeatedly re-encoding with
        add_audio(mix=True).
        """
        from ..audio_mix_inputs import parse_mix_sounds
        from ..engine_audio_mix import mix_audio

        return mix_audio(
            video,
            parse_mix_sounds(tracks, allow_json=False),
            output,
            keep_source=keep_source,
            audio_bitrate=audio_bitrate,
        )

    def duck_audio(
        self,
        video: str,
        music: str,
        output: str | None = None,
        music_volume: float = DEFAULT_DUCK_MUSIC_VOLUME,
        threshold: float = DEFAULT_DUCK_THRESHOLD,
        ratio: float = DEFAULT_DUCK_RATIO,
        attack: float = DEFAULT_DUCK_ATTACK_MS,
        release: float = DEFAULT_DUCK_RELEASE_MS,
    ) -> EditResult:
        """Duck music against the video's audio on plain files, without a project store.

        This sidechain mix provides no governed audio-bed receipt or loudness
        normalization. Use audio_bed with a verified project-store snapshot when
        those guarantees are required.
        """
        from ..engine_audio_ops import duck_audio

        return duck_audio(video, music, output, music_volume, threshold, ratio, attack, release)

    def audio_waveform(
        self,
        video: str,
        bins: int = 50,
    ) -> WaveformResult:
        """Extract audio waveform data (peaks and silence regions)."""
        return _audio_waveform(video, bins=bins)

    def audio_synthesize(
        self,
        output: str,
        waveform: Literal["sine", "square", "sawtooth", "triangle", "noise"] = "sine",
        frequency: float = 440.0,
        duration: float = 1.0,
        volume: float = 0.5,
        effects: dict | None = None,
    ) -> EditResult:
        """Generate audio procedurally using synthesis.

        Args:
            output: Output WAV file path
            waveform: Type of waveform (sine, square, sawtooth, triangle, noise)
            frequency: Base frequency in Hz
            duration: Duration in seconds
            volume: Amplitude (0-1)
            effects: Optional effects dict with envelope, fade_in, fade_out, reverb, lowpass

        Returns:
            Path to generated WAV file
        """
        from ..audio_engine import audio_synthesize

        return audio_synthesize(
            output=output,
            waveform=waveform,
            frequency=frequency,
            duration=duration,
            volume=volume,
            effects=effects,
        )

    def audio_preset(
        self,
        preset: str,
        output: str | None = None,
        pitch: Literal["low", "mid", "high"] = "mid",
        duration: float | None = None,
        intensity: float = 0.5,
        *,
        output_path: str | None = None,
    ) -> EditResult:
        """Generate preset sound design elements.

        Presets: ui-blip, ui-click, ui-tap, ui-whoosh-up, ui-whoosh-down,
                 drone-low, drone-mid, drone-tech, drone-ominous,
                 chime-success, chime-error, chime-notification,
                 typing, scan, processing, data-flow,
                 upload, download

        Returns:
            Path to generated WAV file
        """
        from ..audio_engine import audio_preset

        if output_path is None:
            raise MCPVideoError(
                "audio_preset() requires output_path= (or legacy output=) so agents can read result.output_path.",
                error_type="validation_error",
                code="missing_output_path",
            )
        return audio_preset(
            preset=preset,
            output=output_path,
            pitch=pitch,
            duration=duration,
            intensity=intensity,
        )

    def audio_sequence(
        self,
        sequence: list[dict],
        output: str,
    ) -> EditResult:
        """Compose multiple audio events into a timed sequence.

        Args:
            sequence: List of audio events with type, at (time), duration, etc.
            output: Output WAV file path

        Returns:
            Path to generated WAV file
        """
        if not sequence:
            raise MCPVideoError("sequence cannot be empty", error_type="validation_error", code="empty_sequence")
        from ..audio_engine import audio_sequence

        return audio_sequence(sequence=sequence, output=output)

    def audio_compose(
        self,
        tracks: list[dict],
        duration: float,
        output: str,
    ) -> EditResult:
        """Layer multiple audio tracks with mixing.

        Args:
            tracks: List of track configs. Each dict has keys:
                - file (str): Absolute path to WAV file (required)
                - volume (float): Volume multiplier 0-1 (default 1.0)
                - start (float): Start time offset in seconds (default 0.0)
                - loop (bool): Whether to loop the track (default False)
            duration: Total duration of output in seconds
            output: Output WAV file path

        CLI equivalent: mcp-video audio-compose --tracks '<json>' ...

        Returns:
            Path to generated WAV file
        """
        if not tracks:
            raise MCPVideoError("tracks cannot be empty", error_type="validation_error", code="empty_tracks")
        if duration <= 0:
            raise MCPVideoError("duration must be > 0", error_type="validation_error", code="invalid_parameter")
        for i, track in enumerate(tracks):
            if not isinstance(track, dict):
                raise MCPVideoError(
                    f"tracks[{i}] must be a dict", error_type="validation_error", code="invalid_parameter"
                )
            track_file = track.get("file")
            if not track_file or not isinstance(track_file, str):
                raise MCPVideoError(
                    f"tracks[{i}].file must be a non-empty path string",
                    error_type="validation_error",
                    code="invalid_parameter",
                )
        from ..audio_engine import audio_compose

        return audio_compose(tracks=tracks, duration=duration, output=output)

    def audio_effects(
        self,
        input_path: str,
        output: str,
        effects: list[dict],
    ) -> EditResult:
        """Apply audio effects chain.

        Args:
            input_path: Input WAV file path
            output: Output WAV file path
            effects: List of effect configs with type and parameters

        Returns:
            Path to processed WAV file
        """
        from ..audio_engine import audio_effects

        return audio_effects(input_path=input_path, output=output, effects=effects)

    def add_generated_audio(
        self,
        video: str,
        audio_config: dict,
        output: str,
    ) -> EditResult:
        """Add generated audio to a video file.

        Args:
            video: Input video path
            audio_config: Configuration with drone and/or events
            output: Output video path

        Returns:
            Path to output video
        """
        from ..audio_engine import add_generated_audio

        return add_generated_audio(video=video, audio_config=audio_config, output=output)

    # ------------------------------------------------------------------
    # Visual Effects (P1 Features)
    # ------------------------------------------------------------------

    def audio_spatial(self, video: str, output: str, positions: list[dict], method: str = "hrtf") -> EditResult:
        """Apply 3D spatial audio positioning."""
        from ..ai_engine import audio_spatial

        return audio_spatial(video, output, positions, method)

    def sound_capabilities(self) -> dict[str, Any]:
        """Discover the public sound operation set."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-capabilities")

    def sound_plan_validate(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate a SoundPlan payload (or a built-in minimal plan)."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-plan-validate", plan=plan)

    def sound_voice_batch(
        self,
        plan: dict[str, Any] | None = None,
        *,
        request: dict[str, Any] | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        """Retain local caption speech from a request, or run the synthetic plan demo."""
        from kinocut_sound.public import invoke_sound_operation

        if request is None and project_root is None:
            return invoke_sound_operation("sound-voice-batch", plan=plan)
        return invoke_sound_operation("sound-voice-batch", plan=plan, request=request, project_root=project_root)

    def sound_mix_render(
        self, request: dict[str, Any] | None = None, project_root: str | None = None
    ) -> dict[str, Any]:
        """Assemble supplied WAVs into a new ZIP; omit both arguments for a demo."""
        from kinocut_sound.public import invoke_sound_operation

        if request is None and project_root is None:
            return invoke_sound_operation("sound-mix-render")
        return invoke_sound_operation("sound-mix-render", request=request, project_root=project_root)

    def sound_master_render(self, request: dict[str, Any], project_root: str) -> dict[str, Any]:
        """Retain a two-pass master only after final measured policy compliance."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-master-render", request=request, project_root=project_root)

    def sound_qa_loudness(
        self, wav_bytes: bytes | None = None, *, request=None, project_root=None, delivery=None
    ) -> dict[str, Any]:
        """Measure supplied audio and report actual compliance; omit inputs for a demo."""
        from kinocut.sound_joins.loudness import invoke_sound_operation

        arguments: dict[str, Any] = {}
        if request is not None or project_root is not None:
            arguments.update(request=request, project_root=project_root)
        if wav_bytes is not None:
            arguments["wav_bytes"] = wav_bytes
        if delivery is not None:
            arguments["delivery"] = delivery
        return invoke_sound_operation("sound-qa-loudness", **arguments)

    def sound_qa_asr(
        self,
        *,
        request: dict[str, Any] | str,
        project_root: str,
    ) -> dict[str, Any]:
        """Recognize supplied audio locally against a reference script."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-qa-asr", request=request, project_root=project_root)
