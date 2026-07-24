"""Python client adapters for the thin kinocut_sound S12 public join."""

from __future__ import annotations

from typing import Any


class ClientSoundMixin:
    """Bounded local-first sound discovery and invoke surface."""

    def sound_capabilities(self) -> dict[str, Any]:
        """Discover the public sound operation set."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-capabilities")

    def sound_plan_validate(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate a SoundPlan payload (or a built-in minimal plan)."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-plan-validate", plan=plan)

    def sound_voice_batch(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render a local deterministic voice batch from a SoundPlan."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-voice-batch", plan=plan)

    def sound_mix_render(self) -> dict[str, Any]:
        """Render a bounded local mix for a minimal timeline."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-mix-render")

    def sound_qa_loudness(self) -> dict[str, Any]:
        """Measure loudness against the default delivery policy."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation("sound-qa-loudness")

    def sound_qa_asr(
        self,
        script_hashes: list[str] | None = None,
        audio_duration_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Run the local fake ASR verification port against script hashes."""
        from kinocut_sound.public import invoke_sound_operation

        return invoke_sound_operation(
            "sound-qa-asr",
            script_hashes=script_hashes,
            audio_duration_seconds=audio_duration_seconds,
        )
