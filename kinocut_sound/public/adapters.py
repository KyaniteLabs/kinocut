"""Python adapter surface with privacy-safe JSON-friendly results."""

from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any
from kinocut_sound.public.discovery import discover_sound_capabilities
from kinocut_sound.qa import check_loudness
from kinocut_sound.mix import MixRenderer, MixClip
from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.timeline import Timeline, Cue, CueKind
from kinocut_sound.delivery import DeliveryPolicy


class SoundPythonAdapter:
    """Thin Python facade over stable sound leaves."""

    def capabilities(self) -> dict[str, Any]:
        m = discover_sound_capabilities()
        return {
            "capabilities": list(m.capabilities),
            "flat_commands": list(m.flat_commands),
            "namespaced_commands": list(m.namespaced_commands),
            "non_tty_json": m.non_tty_json,
            "local_first": m.local_first,
        }


def invoke_sound_operation(name: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke a discovered operation by flat or namespaced name."""
    key = name.replace(".", "-") if name.startswith("sound.") else name
    if key in {"sound-capabilities", "sound-capabilities".replace("-", ".")}:
        return SoundPythonAdapter().capabilities()
    if key == "sound-capabilities":
        return SoundPythonAdapter().capabilities()
    if key in {"sound-qa-loudness"}:
        wav = kwargs.get("wav_bytes") or synthesize_tone(duration_seconds=0.2, seed=1)
        rep = check_loudness(wav, DeliveryPolicy())
        return {
            "integrated_lufs": rep.integrated_lufs,
            "true_peak_dbtp": rep.true_peak_dbtp,
            "within_tolerance": rep.within_tolerance,
            "preset": rep.preset,
        }
    if key in {"sound-mix-render"}:
        timeline = Timeline(
            cues=(
                Cue(cue_id="line_1", start_seconds=0.0, duration_seconds=0.2, kind=CueKind.LINE, source_ref="v/a.wav"),
            )
        )
        result = MixRenderer().render(
            timeline=timeline,
            clips=(MixClip(cue_id="line_1", wav_bytes=synthesize_tone(duration_seconds=0.2, seed=2)),),
        )
        return {
            "declared_duration_seconds": result.declared_duration_seconds,
            "measured_duration_seconds": result.measured_duration_seconds,
            "within_tolerance": result.within_tolerance,
            "stem_ids": list(result.stems.stems.keys()),
        }
    raise KeyError(f"unknown sound operation: {name}")
