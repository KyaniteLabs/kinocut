"""CLI handlers for the thin kinocut_sound S12 public join."""

from __future__ import annotations

import json
from typing import Any

from .runner import CommandRunner, _out


def _invoke(name: str, **kwargs: Any) -> dict[str, Any]:
    from kinocut_sound.public import invoke_sound_operation

    return invoke_sound_operation(name, **kwargs)


def _load_plan_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        return json.loads(text)
    # Path to a JSON plan file
    from pathlib import Path

    path = Path(text)
    return json.loads(path.read_text(encoding="utf-8"))


def handle_sound_commands(args: Any, *, use_json: bool) -> bool:
    runner = CommandRunner(args, use_json)

    def _caps(_a, j):
        _out(_invoke("sound-capabilities"), j)

    def _plan(a, j):
        plan = _load_plan_json(getattr(a, "plan_json", None))
        _out(_invoke("sound-plan-validate", plan=plan), j)

    def _voice(a, j):
        plan = _load_plan_json(getattr(a, "plan_json", None))
        _out(_invoke("sound-voice-batch", plan=plan), j)

    def _mix(_a, j):
        _out(_invoke("sound-mix-render"), j)

    def _loud(_a, j):
        _out(_invoke("sound-qa-loudness"), j)

    def _asr(a, j):
        hashes = getattr(a, "script_hashes", None)
        duration = getattr(a, "audio_duration_seconds", 1.0)
        _out(
            _invoke(
                "sound-qa-asr",
                script_hashes=hashes,
                audio_duration_seconds=duration,
            ),
            j,
        )

    runner.register("sound-capabilities", _caps)
    runner.register("sound-plan-validate", _plan)
    runner.register("sound-voice-batch", _voice)
    runner.register("sound-mix-render", _mix)
    runner.register("sound-qa-loudness", _loud)
    runner.register("sound-qa-asr", _asr)
    return runner.dispatch()
