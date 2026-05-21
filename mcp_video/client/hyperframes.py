"""mcp-video Python client — Hyperframes operations mixin."""

from __future__ import annotations

from typing import Any

from ..errors import MCPVideoError


class ClientHyperframesMixin:
    """Hyperframes operations mixin."""

    def hyperframes_render(
        self,
        project_path: str,
        output: str | None = None,
        fps: float | None = None,
        width: int | None = None,
        height: int | None = None,
        composition: str | None = None,
        quality: str | None = None,
        format: str | None = None,
        resolution: str | None = None,
        workers: str | int | None = None,
        crf: int | None = None,
        variables: Any | None = None,
        variables_file: str | None = None,
    ) -> dict:
        """Render a Hyperframes composition to video."""
        from ..hyperframes_engine import render

        return render(
            project_path,
            output_path=output,
            fps=fps,
            width=width,
            height=height,
            composition=composition,
            quality=quality,
            format=format,
            resolution=resolution,
            workers=workers,
            crf=crf,
            variables=variables,
            variables_file=variables_file,
        )

    def hyperframes_compositions(self, project_path: str) -> dict:
        """List compositions in a Hyperframes project."""
        from ..hyperframes_engine import compositions

        return compositions(project_path)

    def hyperframes_preview(self, project_path: str, port: int = 3002) -> dict:
        """Launch Hyperframes preview studio for live preview."""
        from ..hyperframes_engine import preview

        return preview(project_path, port=port)

    def hyperframes_still(
        self,
        project_path: str,
        output: str | None = None,
        frame: int = 0,
        variables: Any | None = None,
        variables_file: str | None = None,
    ) -> dict:
        """Render a single frame as image."""
        from ..hyperframes_engine import still

        return still(project_path, output_path=output, frame=frame, variables=variables, variables_file=variables_file)

    def hyperframes_snapshot(
        self,
        project_path: str,
        frames: int = 5,
        at: list[float] | None = None,
        timeout_ms: int | None = None,
        variables: Any | None = None,
        variables_file: str | None = None,
    ) -> dict:
        """Capture key frames as PNG screenshots for visual verification."""
        from ..hyperframes_engine import snapshot

        return snapshot(
            project_path,
            frames=frames,
            at=at,
            timeout_ms=timeout_ms,
            variables=variables,
            variables_file=variables_file,
        )

    def hyperframes_inspect(
        self,
        project_path: str,
        samples: int = 9,
        at: list[float] | None = None,
        tolerance: int = 2,
        timeout_ms: int | None = None,
        max_issues: int = 80,
        strict: bool = False,
    ) -> dict:
        """Inspect rendered layout for text/container overflow."""
        from ..hyperframes_engine import inspect

        return inspect(
            project_path,
            samples=samples,
            at=at,
            tolerance=tolerance,
            timeout_ms=timeout_ms,
            max_issues=max_issues,
            strict=strict,
        )

    def hyperframes_info(self, project_path: str) -> dict:
        """Return Hyperframes project metadata."""
        from ..hyperframes_engine import info

        return info(project_path)

    def hyperframes_catalog(self, item_type: str | None = None, tag: str | None = None) -> dict:
        """Browse Hyperframes catalog blocks/components."""
        from ..hyperframes_engine import catalog

        return catalog(item_type=item_type, tag=tag)

    def hyperframes_capture(
        self,
        url: str,
        output: str | None = None,
        skip_assets: bool = False,
        max_screenshots: int | None = None,
        timeout_ms: int | None = None,
    ) -> dict:
        """Capture a website as editable Hyperframes components."""
        from ..hyperframes_engine import capture

        return capture(
            url,
            output=output,
            skip_assets=skip_assets,
            max_screenshots=max_screenshots,
            timeout_ms=timeout_ms,
        )

    def hyperframes_tts(
        self,
        text_or_file: str | None = None,
        output: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        language: str | None = None,
        list_voices: bool = False,
    ) -> dict:
        """Generate local speech audio or list available Hyperframes TTS voices."""
        from ..hyperframes_engine import tts

        return tts(
            text_or_file,
            output_path=output,
            voice=voice,
            speed=speed,
            language=language,
            list_voices=list_voices,
        )

    def hyperframes_transcribe(
        self,
        input_path: str,
        project_path: str | None = None,
        model: str | None = None,
        language: str | None = None,
    ) -> dict:
        """Transcribe media to word-level timestamps or import transcripts."""
        from ..hyperframes_engine import transcribe

        return transcribe(input_path, project_path=project_path, model=model, language=language)

    def hyperframes_remove_background(
        self,
        input_path: str,
        output: str | None = None,
        background_output: str | None = None,
        device: str = "auto",
        quality: str = "balanced",
        info: bool = False,
    ) -> dict:
        """Remove a video/image background with Hyperframes local AI."""
        from ..hyperframes_engine import remove_background

        return remove_background(
            input_path,
            output_path=output,
            background_output_path=background_output,
            device=device,
            quality=quality,
            info=info,
        )

    def hyperframes_doctor(self) -> dict:
        """Run Hyperframes environment diagnostics."""
        from ..hyperframes_engine import doctor

        return doctor()

    def hyperframes_benchmark(
        self,
        project_path: str,
        output: str | None = None,
        runs: int | None = None,
        json_output: bool = True,
    ) -> dict:
        """Benchmark Hyperframes render speed and file size."""
        from ..hyperframes_engine import benchmark

        return benchmark(project_path, output_path=output, runs=runs, json_output=json_output)

    def hyperframes_init(
        self,
        name: str,
        output_dir: str | None = None,
        template: str = "blank",
        video: str | None = None,
        audio: str | None = None,
        skip_transcribe: bool = False,
        model: str | None = None,
        language: str | None = None,
        tailwind: bool = False,
        resolution: str | None = None,
    ) -> dict:
        """Scaffold a new Hyperframes project.

        Args:
            name: Project name
            output_dir: Directory to create project in (default: current dir)
            template: Project template (blank, warm-grain, swiss-grid)

        Returns:
            dict with key "project_path" (str): absolute path to the new project
        """
        if not name:
            raise MCPVideoError("name cannot be empty", error_type="validation_error", code="empty_name")
        from ..hyperframes_engine import create_project

        return create_project(
            name,
            output_dir=output_dir,
            template=template,
            video=video,
            audio=audio,
            skip_transcribe=skip_transcribe,
            model=model,
            language=language,
            tailwind=tailwind,
            resolution=resolution,
        )

    def hyperframes_add_block(
        self,
        project_path: str,
        block_name: str,
        no_clipboard: bool = False,
    ) -> dict:
        """Install a block from the Hyperframes catalog."""
        from ..hyperframes_engine import add_block

        return add_block(project_path, block_name, no_clipboard=no_clipboard)

    def hyperframes_validate(self, project_path: str) -> dict:
        """Validate project for rendering readiness.

        Args:
            project_path: Path to the Hyperframes project directory

        Returns:
            HyperframesValidationResult with pass/fail status and issues list
        """
        from ..hyperframes_engine import validate

        return validate(project_path)

    def hyperframes_to_mcpvideo(
        self,
        project_path: str,
        post_process: list[dict],
        output: str | None = None,
    ) -> dict:
        """Render a Hyperframes composition then post-process with mcp-video tools.

        Args:
            project_path: Path to the Hyperframes project directory
            post_process: List of post-processing operations. Each op has "op" (str) and
                optional "params" (dict). Valid op values: resize, convert, add_audio,
                normalize_audio, add_text, fade, watermark
            output: Output file path (auto-generated if omitted)

        Returns:
            HyperframesPipelineResult with output path and applied operations
        """
        from ..hyperframes_engine import render_and_post

        return render_and_post(project_path, post_process, output_path=output)
