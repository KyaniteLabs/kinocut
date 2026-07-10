"""Characterization tests for public import and command surfaces."""

import re
import subprocess
import sys
import asyncio
import json
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


PUBLIC_SURFACE_STATIC_PATHS = (
    ROOT / ".cursorrules",
    ROOT / ".windsurfrules",
    ROOT / ".github" / "copilot-instructions.md",
    ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml",
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SUPPORT.md",
    ROOT / "SECURITY.md",
    ROOT / "ROADMAP.md",
    ROOT / "index.html",
    ROOT / "llms.txt",
    ROOT / "robots.txt",
    ROOT / "sitemap.xml",
    ROOT / "pyproject.toml",
    ROOT / "server.json",
    ROOT / "skills" / "kinocut" / "SKILL.md",
    ROOT / "skills" / "mcp-video" / "SKILL.md",
)


def _public_surface_paths() -> list[Path]:
    """Return every maintained public/discovery surface covered by drift guards."""
    docs_paths = sorted((ROOT / "docs").rglob("*.md"))
    return [path for path in (*PUBLIC_SURFACE_STATIC_PATHS, *docs_paths) if path.exists()]


def _read_public_surfaces() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8") for path in _public_surface_paths()}


EXPECTED_CLI_COMMANDS = {
    "doctor",
    "info",
    "extract-frame",
    "trim",
    "merge",
    "add-text",
    "add-audio",
    "resize",
    "speed",
    "convert",
    "thumbnail",
    "preview",
    "storyboard",
    "subtitles",
    "watermark",
    "crop",
    "rotate",
    "fade",
    "export",
    "extract-audio",
    "edit",
    "filter",
    "blur",
    "reverse",
    "chroma-key",
    "color-grade",
    "normalize-audio",
    "overlay-video",
    "split-screen",
    "batch",
    "detect-scenes",
    "create-from-images",
    "export-frames",
    "compare-quality",
    "read-metadata",
    "write-metadata",
    "stabilize",
    "apply-mask",
    "audio-waveform",
    "generate-subtitles",
    "templates",
    "template",
    "hyperframes-render",
    "hyperframes-compositions",
    "hyperframes-preview",
    "hyperframes-still",
    "hyperframes-snapshot",
    "hyperframes-inspect",
    "hyperframes-info",
    "hyperframes-catalog",
    "hyperframes-capture",
    "hyperframes-tts",
    "hyperframes-transcribe",
    "hyperframes-remove-background",
    "hyperframes-doctor",
    "hyperframes-benchmark",
    "hyperframes-init",
    "hyperframes-add-block",
    "hyperframes-validate",
    "hyperframes-pipeline",
    "repurpose-plan",
    "repurpose",
    "effect-vignette",
    "effect-glow",
    "effect-noise",
    "effect-scanlines",
    "effect-chromatic-aberration",
    "transition-glitch",
    "transition-morph",
    "transition-pixelate",
    "video-ai-transcribe",
    "video-analyze",
    "video-ai-upscale",
    "video-ai-stem-separation",
    "video-ai-scene-detect",
    "video-ai-color-grade",
    "video-ai-remove-silence",
    "audio-synthesize",
    "audio-compose",
    "audio-preset",
    "audio-sequence",
    "audio-effects",
    "video-text-animated",
    "video-mograph-count",
    "video-mograph-progress",
    "video-layout-grid",
    "video-layout-pip",
    "composite-layers",
    "video-add-generated-audio",
    "video-audio-spatial",
    "video-auto-chapters",
    "video-extract-frame",
    "video-info-detailed",
    "video-quality-check",
    "video-design-quality-check",
    "video-fix-design-issues",
    "image-extract-colors",
    "image-generate-palette",
    "image-analyze-product",
    "workflow-validate",
    "workflow-plan",
    "workflow-render",
    "workflow-inspect",
    "rescue-plan",
    "rescue-render",
    "rescue-inspect",
    "semantic-timeline",
    "semantic-query",
    "timeline-edit-plan",
    "visual-transform-plan",
    "restoration-plan",
    "composition-plan",
    "creative-autopilot-plan",
    "remote-egress-plan",
}

EXPECTED_SERVER_TOOLS = {
    "video_info",
    "video_trim",
    "video_merge",
    "video_add_text",
    "video_add_audio",
    "video_resize",
    "video_convert",
    "video_speed",
    "search_tools",
    "video_thumbnail",
    "video_preview",
    "video_storyboard",
    "video_subtitles",
    "video_watermark",
    "video_export",
    "video_crop",
    "video_rotate",
    "video_fade",
    "video_edit",
    "video_extract_audio",
    "video_filter",
    "video_reverse",
    "video_chroma_key",
    "video_normalize_audio",
    "video_overlay",
    "video_composite_layers",
    "video_split_screen",
    "video_batch",
    "video_cleanup",
    "video_detect_scenes",
    "video_template_preview",
    "video_create_from_images",
    "video_export_frames",
    "video_generate_subtitles",
    "video_compare_quality",
    "video_read_metadata",
    "video_write_metadata",
    "video_stabilize",
    "video_apply_mask",
    "video_audio_waveform",
    "hyperframes_render",
    "hyperframes_compositions",
    "hyperframes_preview",
    "hyperframes_still",
    "hyperframes_snapshot",
    "hyperframes_inspect",
    "hyperframes_info",
    "hyperframes_catalog",
    "hyperframes_capture",
    "hyperframes_tts",
    "hyperframes_transcribe",
    "hyperframes_remove_background",
    "hyperframes_doctor",
    "hyperframes_benchmark",
    "hyperframes_init",
    "hyperframes_add_block",
    "hyperframes_validate",
    "hyperframes_to_mcpvideo",
    "video_repurpose_plan",
    "video_repurpose",
    "audio_synthesize",
    "audio_preset",
    "audio_sequence",
    "audio_compose",
    "audio_effects",
    "video_add_generated_audio",
    "effect_vignette",
    "effect_chromatic_aberration",
    "effect_scanlines",
    "effect_noise",
    "effect_glow",
    "video_text_animated",
    "video_subtitles_styled",
    "video_mograph_count",
    "video_mograph_progress",
    "video_layout_grid",
    "video_layout_pip",
    "video_auto_chapters",
    "video_info_detailed",
    "transition_glitch",
    "transition_pixelate",
    "transition_morph",
    "video_ai_remove_silence",
    "video_ai_transcribe",
    "video_analyze",
    "video_ai_scene_detect",
    "video_ai_stem_separation",
    "video_ai_upscale",
    "video_ai_color_grade",
    "video_audio_spatial",
    "video_quality_check",
    "video_release_checkpoint",
    "video_design_quality_check",
    "video_fix_design_issues",
    "image_extract_colors",
    "image_generate_palette",
    "image_analyze_product",
    "video_project_create",
    "style_pack_read",
    "storyboard_read",
    "shot_prompt_render",
    "video_add_texts",
    "video_validate_text_layout",
    "video_extract_frame",
    "video_duck_audio",
    "video_workflow_validate",
    "video_workflow_plan",
    "video_workflow_render",
    "video_workflow_inspect",
    "video_rescue_plan",
    "video_rescue_render",
    "video_rescue_inspect",
    "video_semantic_timeline",
    "video_semantic_query",
    "video_timeline_edit_plan",
    "video_visual_transform_plan",
    "video_restoration_plan",
    "video_composition_plan",
    "video_creative_autopilot_plan",
    "video_remote_egress_plan",
}


def test_cli_help_lists_all_commands():
    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    command_lists = re.findall(r"\{([^}]+)\}", result.stdout)
    command_list = max(command_lists, key=lambda value: len(value.split(",")))
    help_commands = set(command_list.split(","))

    assert help_commands == EXPECTED_CLI_COMMANDS
    assert len(EXPECTED_CLI_COMMANDS) == 114


def test_agent_cookbook_dry_run():
    result = subprocess.run(
        [sys.executable, "examples/agent_cookbook.py", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "Inspect create_from_images" in result.stdout
    assert "video_release_checkpoint" in result.stdout


def test_server_tool_registry_keeps_public_tool_names():
    from mcp_video.server import mcp

    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert tool_names >= EXPECTED_SERVER_TOOLS
    assert len(tool_names) == 135


def test_hyperframes_tts_schema_can_list_voices_without_text():
    from mcp_video.server import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["hyperframes_tts"].inputSchema

    assert "list_voices" in schema["properties"]
    assert "text_or_file" not in schema.get("required", [])


def test_stdio_server_launches_and_lists_tools_like_registry_clients():
    """Exercise the package the way registries launch it: stdio subprocess + MCP handshake."""

    async def check_server() -> None:
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_video"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init_result = await session.initialize()
            tools_result = await session.list_tools()

        tool_names = {tool.name for tool in tools_result.tools}
        assert init_result.serverInfo.name == "mcp-video"
        assert tool_names >= EXPECTED_SERVER_TOOLS
        assert len(tool_names) == 135

    asyncio.run(check_server())


def _call_tool_over_stdio(tool_name: str, arguments: dict):
    """Round-trip a tool call the way real MCP clients do: stdio + serialization."""

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_video"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

    return asyncio.run(run())


def _structured_payload(result) -> dict:
    if result.structuredContent:
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_call_tool_round_trip_video_info(sample_video):
    """list_tools alone cannot catch a schema/serialization regression —
    only an actual call_tool round trip exercises the wire format."""
    result = _call_tool_over_stdio("video_info", {"input_path": sample_video})

    assert result.isError is False
    payload = _structured_payload(result)
    assert payload["success"] is True
    assert payload["info"]["duration"] > 0


def test_call_tool_round_trip_video_trim(sample_video, tmp_path):
    out = str(tmp_path / "rt_trim.mp4")
    result = _call_tool_over_stdio(
        "video_trim",
        {"input_path": sample_video, "start": "0", "duration": "1", "output_path": out},
    )

    assert result.isError is False
    payload = _structured_payload(result)
    assert payload["success"] is True
    assert Path(out).is_file()


def test_call_tool_round_trip_returns_structured_error_for_bad_input():
    result = _call_tool_over_stdio("video_info", {"input_path": "/nonexistent/clip.mp4"})

    payload = _structured_payload(result)
    assert payload["success"] is False
    assert "error" in payload


def test_public_discovery_files_do_not_point_at_old_personal_namespace():
    checked_paths = [
        *_public_surface_paths(),
        ROOT / "scripts" / "github-pr-monitor.py",
        ROOT / "kinocut" / "ai_engine" / "download.py",
        ROOT / "kinocut" / "errors.py",
    ]
    stale_fragments = [
        "pastor" + "simon1798.github.io/mcp-video",
        "github.com/" + "pastor" + "simon1798/mcp-video",
        "github.com/" + "Pastor" + "simon1798/mcp-video",
        "io.github." + "pastor" + "simon1798/mcp-video",
    ]

    offenders = {
        str(path.relative_to(ROOT)): fragment
        for path in checked_paths
        for fragment in stale_fragments
        if path.exists() and fragment in path.read_text(encoding="utf-8")
    }

    assert offenders == {}


def test_server_json_and_readme_match_registry_identity():
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert server["name"] == "io.github.KyaniteLabs/kinocut"
    assert server["websiteUrl"] == "https://kinocut.dev/"
    # The registry's semantic validator currently accepts the GitHub mirror,
    # while Forgejo remains the canonical repository on every other surface.
    assert server["repository"]["url"] == "https://github.com/KyaniteLabs/kinocut"
    assert server["repository"]["source"] == "github"
    assert server["packages"][0]["identifier"] == "kinocut"
    assert server["packages"][0]["runtimeHint"] == "uvx"
    assert server["packages"][0]["transport"]["type"] == "stdio"
    assert f"mcp-name: {server['name']}" in readme


def test_public_tree_does_not_track_local_agent_state_artifacts():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    local_state_prefixes = (".pi-lens/", ".pi/")

    assert [path for path in tracked if path.startswith(local_state_prefixes)] == []


def test_public_guidance_does_not_expose_local_runtime_details():
    forbidden = [
        "/" + "Users/",
        "100." + "66.225.85",
        "simon" + "@puenteworks.com",
        ".pi-lens" + "/cache",
    ]

    offenders = {
        path: fragment for path, text in _read_public_surfaces().items() for fragment in forbidden if fragment in text
    }

    assert offenders == {}


def test_canonical_public_surfaces_point_to_renamed_repository():
    forbidden = [
        "github.com/KyaniteLabs/mcp-video",
        "git.kyanitelabs.tech/KyaniteLabs/mcp-video",
        "kyanitelabs.github.io/mcp-video",
        "GitHub Security Advisories",
        "View on GitHub",
        "See GitHub for full list",
        "v1.4.0",
    ]

    checked_surfaces = _read_public_surfaces()
    offenders = {path: fragment for path, text in checked_surfaces.items() for fragment in forbidden if fragment in text}

    assert offenders == {}


def test_publish_workflow_has_registry_only_recovery_path():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "needs.publish.result == 'success'" in workflow


def test_public_surface_manifest_covers_agent_discovery_files():
    public_paths = {str(path.relative_to(ROOT)) for path in _public_surface_paths()}

    assert "llms.txt" in public_paths
    assert "docs/AI_AGENT_DISCOVERY.md" in public_paths
    assert "skills/kinocut/SKILL.md" in public_paths
    assert "skills/mcp-video/SKILL.md" in public_paths
    assert "ROADMAP.md" in public_paths


def test_public_site_matches_release_identity():
    site = (ROOT / "index.html").read_text(encoding="utf-8")

    assert '<link rel="canonical" href="https://kinocut.dev/">' in site
    assert 'content="0; url=https://kinocut.dev/"' in site
    assert 'href="https://kinocut.dev/"' in site
    assert "mcp-video is now Kinocut" in site


def test_heavy_ai_extras_keep_python313_installable():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_deps = pyproject["project"]["optional-dependencies"]

    for extra in ("upscale", "ai", "all-ai"):
        dependencies = optional_deps[extra]
        assert "opencv-contrib-python>=4.10" in dependencies
        assert "realesrgan>=0.3; python_version < '3.13'" in dependencies
        assert "basicsr>=1.4; python_version < '3.13'" in dependencies

    for extra in ("audio-ai", "audio-all"):
        assert "numpy>=1.24" in optional_deps[extra]
        assert all(not dependency.startswith("basic-pitch") for dependency in optional_deps[extra])


def test_optional_extras_do_not_advertise_unpublished_dependencies():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_deps = pyproject["project"]["optional-dependencies"]
    dependency_text = "\n".join(dependency for dependencies in optional_deps.values() for dependency in dependencies)

    assert "meltysynth" not in dependency_text
    assert "basic-pitch" not in dependency_text


def test_module_reexports():
    """Engine and server modules preserve expected import targets."""
    import mcp_video.server as server
    import mcp_video.engine as engine

    for name in [
        "_error_result",
        "_result",
        "templates_resource",
        "video_info_resource",
        "video_preview_resource",
        "video_audio_resource",
        "video_trim",
        "video_analyze",
        "hyperframes_render",
        "hyperframes_snapshot",
        "video_repurpose_plan",
        "image_analyze_product",
        "video_project_create",
        "shot_prompt_render",
    ]:
        assert hasattr(server, name), f"server missing {name}"

    for name in [
        "_check_filter_available",
        "_escape_ffmpeg_filter_value",
        "_generate_thumbnail_base64",
        "_get_color_preset_filter",
        "_parse_ffmpeg_time",
        "_run_ffmpeg_with_progress",
        "_validate_color",
        "_validate_position",
        "add_text",
        "convert",
        "resize",
        "trim",
        "video_batch",
    ]:
        assert hasattr(engine, name), f"engine missing {name}"


def test_hyperframes_runtime_data_public_signatures():
    """Hyperframes runtime-data controls stay visible on public tool surfaces."""
    import inspect

    from mcp_video import server_tools_hyperframes as tools
    from mcp_video.client import Client

    server_methods = [tools.hyperframes_render, tools.hyperframes_still, tools.hyperframes_snapshot]
    client = Client()
    client_methods = [client.hyperframes_render, client.hyperframes_still, client.hyperframes_snapshot]

    for method in [*server_methods, *client_methods]:
        params = inspect.signature(method).parameters
        assert "variables" in params
        assert "variables_file" in params
