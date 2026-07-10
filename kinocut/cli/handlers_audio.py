"""CLI handlers for audio synthesis and audio-video commands."""

from __future__ import annotations

from typing import Any

from .common import _parse_json_arg, _with_spinner
from .formatting import _format_path_panel
from .runner import CommandRunner, _out


def handle_audio_commands(args: Any, *, use_json: bool) -> bool:
    """Handle audio synthesis and spatial commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _synthesize(a, j):
        from ..audio_engine import audio_synthesize

        effects = _parse_json_arg(a.effects, "effects", json_mode=j) if a.effects else None
        r = _with_spinner(
            "Synthesizing audio...",
            audio_synthesize,
            a.output,
            waveform=a.waveform,
            frequency=a.frequency,
            duration=a.duration,
            volume=a.volume,
            effects=effects,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel("Audio synthesized", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("audio-synthesize", _synthesize)

    def _compose(a, j):
        from ..audio_engine import audio_compose

        tracks = _parse_json_arg(a.tracks, "tracks", json_mode=j)
        r = _with_spinner("Composing audio...", audio_compose, tracks, a.duration, a.output)
        _out(
            r,
            j,
            lambda res: _format_path_panel("Audio composed", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("audio-compose", _compose)

    def _preset(a, j):
        from ..audio_engine import audio_preset

        r = _with_spinner(
            f"Generating preset '{a.preset}'...",
            audio_preset,
            a.preset,
            a.output,
            pitch=a.pitch,
            duration=a.duration,
            intensity=a.intensity,
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Preset '{a.preset}'", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("audio-preset", _preset)

    def _sequence(a, j):
        from ..audio_engine import audio_sequence

        sequence = _parse_json_arg(a.sequence, "sequence", json_mode=j)
        r = _with_spinner("Composing audio sequence...", audio_sequence, sequence, a.output)
        _out(
            r,
            j,
            lambda res: _format_path_panel("Audio sequence", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("audio-sequence", _sequence)

    def _effects(a, j):
        from ..audio_engine import audio_effects

        effects = _parse_json_arg(a.effects, "effects", json_mode=j)
        r = _with_spinner("Applying audio effects...", audio_effects, a.input, a.output, effects)
        _out(
            r,
            j,
            lambda res: _format_path_panel("Audio effects applied", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("audio-effects", _effects)

    def _add_generated(a, j):
        from ..audio_engine import add_generated_audio

        audio_config = _parse_json_arg(a.audio_config, "audio-config", json_mode=j)
        r = _with_spinner("Adding generated audio...", add_generated_audio, a.input, audio_config, a.output)
        _out(
            r,
            j,
            lambda res: _format_path_panel("Generated audio added", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-add-generated-audio", _add_generated)

    def _spatial(a, j):
        from ..ai_engine import audio_spatial

        positions = _parse_json_arg(a.positions, "positions", json_mode=j)
        r = _with_spinner(
            "Applying spatial audio...", audio_spatial, a.input, a.output, positions=positions, method=a.method
        )
        _out(
            r,
            j,
            lambda res: _format_path_panel(f"Spatial audio ({a.method})", res),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-audio-spatial", _spatial)

    return runner.dispatch()
