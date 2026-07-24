"""Python adapter surface with privacy-safe JSON-friendly results."""

from __future__ import annotations

import tempfile
from typing import Any

from pydantic import ValidationError

from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.format import (
    AudioFormat,
    ChannelLayout,
    ConversionPolicy,
    DitherPolicy,
    SampleFormat,
    TimeBase,
)
from kinocut_sound.lines import Emotion, Line, ProfileRef, Prosody
from kinocut_sound.mix import MixClip, MixRenderer
from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.public.discovery import discover_sound_capabilities
from kinocut_sound.qa import FakeAsrPort, check_loudness, verify_script_asr
from kinocut_sound.routing import Routing
from kinocut_sound.sound_plan import PlanProvenance, SoundPlan
from kinocut_sound.timeline import Cue, CueKind, Timeline
from kinocut_sound.voice import BatchPlanner, LocalSynthesisAdapter, default_roster
from kinocut_sound.voice._errors import VoiceError

_SHA_ZERO = "sha256:" + ("0" * 64)

# Flat names are canonical; namespaced dotted forms normalize here.
_KNOWN_OPS = frozenset(
    {
        "sound-capabilities",
        "sound-plan-validate",
        "sound-voice-batch",
        "sound-mix-render",
        "sound-qa-loudness",
        "sound-qa-asr",
    }
)


def _normalize_op(name: str) -> str:
    if name.startswith("sound."):
        # sound.plan.validate -> sound-plan-validate
        return "sound-" + name.removeprefix("sound.").replace(".", "-")
    return name


def _assert_no_host_leak(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if a result would expose absolute host paths or secrets."""
    text = str(payload)
    for marker in ("/Users/", "/home/", "C:\\", "password", "secret_key", "BEGIN PRIVATE"):
        if marker in text:
            raise ValueError("sound operation result rejected: privacy boundary")
    return payload


def _minimal_format() -> AudioFormat:
    return AudioFormat(
        channel_layout=ChannelLayout.MONO,
        sample_rate_hz=22050,
        sample_format=SampleFormat.PCM_S16LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.NONE,
    )


def _minimal_line(*, line_id: str = "line_1", slot_id: str = "hero_tenor") -> Line:
    return Line(
        line_id=line_id,
        character_id="character_a",
        profile=ProfileRef(profile_id=slot_id, version=1),
        text_hash=_SHA_ZERO,
        text_length_chars=16,
        prosody=Prosody(),
        emotion=Emotion(label="neutral", intensity=0.0),
        spatial_preset="close_mic_dry",
        inherit_loudness=True,
    )


def _minimal_plan(**overrides: Any) -> SoundPlan:
    base: dict[str, Any] = {
        "project_id": "proj_public",
        "episode_id": "episode_public",
        "format": _minimal_format(),
        "timeline": Timeline(
            cues=(
                Cue(
                    cue_id="cue_intro",
                    start_seconds=0.0,
                    duration_seconds=0.2,
                    kind=CueKind.SILENCE,
                    source_ref="silence/room_tone.wav",
                ),
            )
        ),
        "lines": (_minimal_line(),),
        "beds": (),
        "layers": (),
        "routing": Routing(),
        "delivery": DeliveryPolicy(),
        "provenance": PlanProvenance(),
        "created_by": "tool:sound_public",
    }
    base.update(overrides)
    return SoundPlan(**base)


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

    def plan_validate(self, plan: dict[str, Any] | SoundPlan | None = None) -> dict[str, Any]:
        try:
            if plan is None:
                validated = _minimal_plan()
            elif isinstance(plan, SoundPlan):
                validated = plan
            else:
                validated = SoundPlan.model_validate(plan)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError("sound plan validation failed") from exc
        return {
            "ok": True,
            "plan_hash": validated.canonical_id(),
            "episode_id": validated.episode_id,
            "line_count": len(validated.lines),
        }

    def voice_batch(self, plan: dict[str, Any] | SoundPlan | None = None) -> dict[str, Any]:
        try:
            if plan is None:
                sound_plan = _minimal_plan()
            elif isinstance(plan, SoundPlan):
                sound_plan = plan
            else:
                sound_plan = SoundPlan.model_validate(plan)
            with tempfile.TemporaryDirectory(prefix="kinocut-sound-batch-") as tmp:
                planner = BatchPlanner(
                    adapter=LocalSynthesisAdapter(),
                    roster=default_roster(),
                    output_dir=tmp,
                )
                result = planner.render_plan(sound_plan)
        except VoiceError as exc:
            raise ValueError(f"sound voice batch failed: {exc.code}") from exc
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError("sound voice batch failed") from exc
        return {
            "ok": True,
            "plan_hash": result.plan_hash,
            "clip_count": len(result.clips),
            "clips": [
                {
                    "cue_id": clip.cue_id,
                    "line_id": clip.line_id,
                    "slot_id": clip.slot_id,
                    "output_path": clip.output_path,  # project-relative only
                    "output_hash": clip.output_hash,
                    "duration_seconds": clip.duration_seconds,
                }
                for clip in result.clips
            ],
            "human_review_required": result.receipt_section.human_review_required,
        }

    def mix_render(self) -> dict[str, Any]:
        timeline = Timeline(
            cues=(
                Cue(
                    cue_id="line_1",
                    start_seconds=0.0,
                    duration_seconds=0.2,
                    kind=CueKind.LINE,
                    source_ref="v/a.wav",
                ),
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

    def qa_loudness(self, wav_bytes: bytes | None = None) -> dict[str, Any]:
        wav = wav_bytes or synthesize_tone(duration_seconds=0.2, seed=1)
        rep = check_loudness(wav, DeliveryPolicy())
        return {
            "integrated_lufs": rep.integrated_lufs,
            "true_peak_dbtp": rep.true_peak_dbtp,
            "within_tolerance": rep.within_tolerance,
            "preset": rep.preset,
        }

    def qa_asr(
        self,
        *,
        script_hashes: tuple[str, ...] | list[str] | None = None,
        audio_duration_seconds: float = 1.0,
        available: bool = True,
    ) -> dict[str, Any]:
        hashes = tuple(script_hashes) if script_hashes else (_SHA_ZERO,)
        try:
            rep = verify_script_asr(
                port=FakeAsrPort(available=available),
                script_hashes=hashes,
                audio_duration_seconds=float(audio_duration_seconds),
            )
        except Exception as exc:
            # Bounded surface: never leak provider internals.
            raise ValueError("sound qa asr failed") from exc
        return {
            "ok": rep.ok,
            "mismatch_count": rep.mismatch_count,
            "segment_count": len(rep.segments),
        }


def invoke_sound_operation(name: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke a discovered operation by flat or namespaced name."""
    key = _normalize_op(name)
    if key not in _KNOWN_OPS:
        raise KeyError(f"unknown sound operation: {name}")

    adapter = SoundPythonAdapter()
    if key == "sound-capabilities":
        result = adapter.capabilities()
    elif key == "sound-plan-validate":
        result = adapter.plan_validate(kwargs.get("plan") or kwargs.get("plan_json"))
    elif key == "sound-voice-batch":
        result = adapter.voice_batch(kwargs.get("plan") or kwargs.get("plan_json"))
    elif key == "sound-mix-render":
        result = adapter.mix_render()
    elif key == "sound-qa-loudness":
        result = adapter.qa_loudness(kwargs.get("wav_bytes"))
    elif key == "sound-qa-asr":
        result = adapter.qa_asr(
            script_hashes=kwargs.get("script_hashes"),
            audio_duration_seconds=kwargs.get("audio_duration_seconds", 1.0),
            available=kwargs.get("available", True),
        )
    else:  # pragma: no cover - guarded by _KNOWN_OPS
        raise KeyError(f"unknown sound operation: {name}")

    return _assert_no_host_leak(result)
