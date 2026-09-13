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
        from kinocut_sound.public import invoke_sound_operation

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
        script_hashes: list[str] | None = None,
        audio_duration_seconds: float = 1.0,
        *,
        request: dict[str, Any] | str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        """Recognize supplied audio locally, or return an explicitly simulated demo."""
        from kinocut_sound.public import invoke_sound_operation

        arguments = dict(script_hashes=script_hashes, audio_duration_seconds=audio_duration_seconds)
        if request is not None or project_root is not None:
            arguments.update(request=request, project_root=project_root)
        return invoke_sound_operation("sound-qa-asr", **arguments)
