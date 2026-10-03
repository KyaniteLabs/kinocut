"""Operator adapters for existing plain-file audio engines."""

from __future__ import annotations

from typing import Any

from ..audio_mix_inputs import parse_mix_sounds
from .common import _with_spinner
from .formatting import _format_edit_text
from .runner import CommandRunner, _out, engine_cmd


def _mix(args: Any, use_json: bool) -> None:
    from ..engine_audio_mix import mix_audio

    result = _with_spinner(
        "Mixing audio...",
        mix_audio,
        args.input,
        parse_mix_sounds(args.sounds),
        output_path=args.output,
        keep_source=args.keep_source,
        audio_bitrate=args.audio_bitrate,
    )
    _out(result, use_json, _format_edit_text)


def handle_audio_mix_commands(args: Any, *, use_json: bool) -> bool:
    """Dispatch mix-audio and duck-audio through the existing media engines."""
    runner = CommandRunner(args, use_json)
    runner.register("mix-audio", _mix)
    runner.register(
        "duck-audio",
        engine_cmd(
            "kinocut.engine_audio_ops:duck_audio",
            "Ducking audio...",
            "input",
            "music",
            formatter=_format_edit_text,
            output_path="output",
            music_volume="music_volume",
            threshold="threshold",
            ratio="ratio",
            attack="attack",
            release="release",
        ),
    )
    return runner.dispatch()
