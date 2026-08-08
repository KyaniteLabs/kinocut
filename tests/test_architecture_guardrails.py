"""Architecture guardrails for the post-remediation module layout."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kinocut"

FACADE_MODULES = {
    "engine.py": {
        "max_lines": 140,
        "allowed_assignments": {"apply_mask", "apply_filter", "overlay_video", "split_screen", "video_batch"},
    },
    "server.py": {
        "max_lines": 180,
        "allowed_assignments": set(),
    },
}


def source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def module_line_count(path: Path) -> int:
    return len(source_lines(path))


def public_engine_modules() -> list[Path]:
    return sorted(PACKAGE.glob("engine*.py"))


def server_modules() -> list[Path]:
    return sorted(PACKAGE.glob("server*.py"))


def test_engine_and_server_facades_stay_thin() -> None:
    """The old giant engine/server files should remain compatibility facades."""
    for relative_path, limits in FACADE_MODULES.items():
        path = PACKAGE / relative_path
        assert module_line_count(path) <= limits["max_lines"], f"{relative_path} is no longer a thin facade"

        tree = parse_module(path)
        definitions = [
            node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ]
        assert definitions == [], f"{relative_path} should re-export/import behavior, not define {definitions}"

        assignments = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert assignments <= limits["allowed_assignments"], f"{relative_path} has unexpected facade assignments"


def test_engine_modules_stay_below_project_size_limit() -> None:
    """No engine module should grow back into the pre-remediation monolith."""
    oversized = {
        path.relative_to(ROOT).as_posix(): module_line_count(path)
        for path in public_engine_modules()
        if module_line_count(path) > 800
    }

    assert oversized == {}


def test_split_engine_modules_stay_below_size_limit() -> None:
    """Modules split out of the hyperframes/workflow monoliths (WP-C) stay ≤800 LOC.

    These were 1302/1000 lines before the split and were not previously guarded,
    which is why they grew. Lock the ceiling so a future addition cannot silently
    undo the split.
    """
    split_modules = [
        PACKAGE / "hyperframes_engine.py",
        PACKAGE / "hyperframes_ops.py",
        PACKAGE / "workflow" / "executor.py",
        PACKAGE / "workflow" / "receipt.py",
    ]
    oversized = {
        path.relative_to(ROOT).as_posix(): module_line_count(path) for path in split_modules if module_line_count(path) > 800
    }
    assert oversized == {}, f"split modules exceeded 800 LOC: {oversized}"


def test_rescue_verifier_functions_stay_below_project_size_limit() -> None:
    """Independent verification checks must remain cohesive and reviewable."""

    path = PACKAGE / "rescue" / "verifier.py"
    oversized = {
        node.name: node.end_lineno - node.lineno + 1
        for node in ast.walk(parse_module(path))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 > 80
    }

    assert oversized == {}


def test_server_modules_stay_below_project_size_limit() -> None:
    """Server registration groups should remain reviewable and split by family."""
    oversized = {
        path.relative_to(ROOT).as_posix(): module_line_count(path)
        for path in server_modules()
        if module_line_count(path) > 800
    }

    assert oversized == {}


def test_engine_operation_modules_do_not_import_compatibility_facade() -> None:
    """Engine implementation modules must not depend on the compatibility facade."""
    offenders: dict[str, list[str]] = {}
    for path in public_engine_modules():
        if path.name == "engine.py":
            continue
        tree = parse_module(path)
        bad_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # Catch: "from engine import …", "from kinocut.engine import …",
                # "from . import engine", "from .engine import …"
                if node.module in {"engine", "kinocut.engine"}:
                    bad_imports.append(f"from {node.module} import ...")
                if node.level and node.level >= 1 and node.module == "engine":
                    bad_imports.append(f"from {'.' * node.level}engine import ...")
                if node.level == 1 and node.module is None:
                    for alias in node.names:
                        if alias.name == "engine":
                            bad_imports.append("from . import engine")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut.engine":
                        bad_imports.append("import kinocut.engine")
        if bad_imports:
            offenders[path.relative_to(ROOT).as_posix()] = bad_imports

    assert offenders == {}


def test_server_tool_modules_register_against_server_app_not_facade() -> None:
    """Tool groups should import mcp from server_app to avoid circular facade coupling."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.glob("server_tools_*.py")):
        tree = parse_module(path)
        bad_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # Catch: "from server import …", "from kinocut.server import …",
                # "from . import server", "from .server import …"
                if node.module in {"server", "kinocut.server"}:
                    bad_imports.append(f"from {node.module} import ...")
                if node.level and node.level >= 1 and node.module == "server":
                    bad_imports.append(f"from {'.' * node.level}server import ...")
                if node.level == 1 and node.module is None:
                    for alias in node.names:
                        if alias.name == "server":
                            bad_imports.append("from . import server")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "kinocut.server":
                        bad_imports.append("import kinocut.server")
        if bad_imports:
            offenders[path.relative_to(ROOT).as_posix()] = bad_imports

    assert offenders == {}


def test_shared_ffmpeg_helpers_remain_canonical_for_core_utilities() -> None:
    """Prevent new copies of the canonical FFmpeg helper utilities."""
    allowed_definitions = {
        "_run_ffmpeg": {"kinocut/ffmpeg_helpers.py"},
        "_get_video_duration": {"kinocut/ffmpeg_helpers.py"},
        "_seconds_to_srt_time": {"kinocut/ffmpeg_helpers.py"},
    }
    definitions = {name: set() for name in allowed_definitions}

    for path in sorted(PACKAGE.glob("*.py")):
        if path.name.startswith("._"):
            continue  # macOS AppleDouble artifacts in tar/Finder-copied trees
        tree = parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in definitions:
                definitions[node.name].add(path.relative_to(ROOT).as_posix())

    assert definitions == allowed_definitions


# ---------------------------------------------------------------------------
# WP-D: function-size guardrail
# ---------------------------------------------------------------------------

#: Maximum function length (body lines) per the project size policy.
FUNCTION_LINE_LIMIT = 80

#: Frozen baseline of functions that already exceed FUNCTION_LINE_LIMIT.
#: As each function is decomposed, remove its entry here so the net tightens.
_FUNCTION_SIZE_BASELINE: dict[str, set[str]] = {
    "kinocut/ai_engine/__init__.py": {"analyze_video"},
    "kinocut/ai_engine/color.py": {"ai_color_grade"},
    "kinocut/ai_engine/scene.py": {"ai_scene_detect"},
    "kinocut/ai_engine/silence.py": {"_concat_segments"},
    "kinocut/ai_engine/spatial.py": {"_apply_simple_spatial"},
    "kinocut/ai_engine/stem.py": {"ai_stem_separation"},
    "kinocut/ai_engine/transcribe.py": {"ai_transcribe"},
    "kinocut/ai_engine/upscale.py": {"ai_upscale"},
    "kinocut/audio_engine/__init__.py": {"add_generated_audio"},
    "kinocut/audio_engine/integrations/meltysynth_bridge.py": {"render_notes"},
    "kinocut/audio_engine/sequencing.py": {"audio_effects"},
    "kinocut/audio_engine/synthesis.py": {"_apply_synth_effects", "audio_synthesize"},
    "kinocut/cli/formatting.py": {"_format_video_analyze"},
    "kinocut/cli/handlers_ai.py": {"handle_ai_commands"},
    "kinocut/cli/handlers_audio.py": {"handle_audio_commands"},
    "kinocut/cli/handlers_composition.py": {"handle_composition_command"},
    "kinocut/cli/handlers_effects.py": {"handle_effect_command"},
    "kinocut/cli/handlers_image.py": {"handle_image_commands"},
    "kinocut/cli/handlers_intent.py": {"handle_intent_commands"},
    "kinocut/cli/parser/advanced.py": {"add_parsers"},
    "kinocut/cli/parser/ai.py": {"add_parsers"},
    "kinocut/cli/parser/audio.py": {"add_parsers"},
    "kinocut/cli/parser/core.py": {"add_parsers"},
    "kinocut/cli/parser/effects.py": {"add_parsers"},
    "kinocut/cli/parser/hyperframes.py": {"add_parsers"},
    "kinocut/cli/parser/image.py": {"add_parsers"},
    "kinocut/cli/parser/intent.py": {"add_parsers"},
    "kinocut/cli/parser/layout.py": {"add_parsers"},
    "kinocut/cli/parser/media.py": {"add_parsers"},
    "kinocut/creative/autopilot.py": {"plan_creative_autopilot"},
    "kinocut/design_guardrails.py": {"validate_text_layout"},
    "kinocut/effects_engine/layout.py": {"layout_grid", "layout_pip"},
    "kinocut/effects_engine/mograph.py": {"mograph_count", "mograph_progress"},
    "kinocut/effects_engine/text.py": {"text_animated"},
    "kinocut/effects_engine/utility.py": {"video_info_detailed"},
    "kinocut/engine_audio_normalize.py": {"normalize_audio"},
    "kinocut/engine_audio_ops.py": {"_build_add_audio_args", "duck_audio"},
    "kinocut/engine_edit.py": {"trim"},
    "kinocut/engine_glitch.py": {"glitch_turbulent_displacement"},
    "kinocut/engine_glitch_shader.py": {"_run_shader_effect"},
    "kinocut/engine_hls.py": {"hls_segment"},
    "kinocut/engine_merge.py": {"_merge_with_transitions", "merge"},
    "kinocut/engine_storyboard.py": {"storyboard"},
    "kinocut/engine_text.py": {"add_text", "add_texts"},
    "kinocut/hyperframes_ops.py": {"render"},
    "kinocut/product/package.py": {"package_approved_clip"},
    "kinocut/product/shorts_review.py": {"resolve_approved_candidate"},
    "kinocut/projectstore/edit_projects.py": {"append_revision"},
    "kinocut/rescue/inspector.py": {"inspect_rescue"},
    "kinocut/semantic/edl.py": {"verify_timeline_diff"},
    "kinocut/server_tools_hyperframes.py": {"hyperframes_render"},
    "kinocut/still_plates/package.py": {"still_package"},
    "kinocut/templates.py": {"preview_template"},
    "kinocut/transitions_engine.py": {"transition_pixelate"},
    "kinocut/watching/metrics.py": {"run_metric_qc"},
    "kinocut/workflow/executor.py": {"_render_one"},
}


def _functions_exceeding_limit() -> dict[str, set[str]]:
    """Return ``{module_path: {function_name}}`` for every function > LIMIT lines."""
    result: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = parse_module(path)
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = node.end_lineno - node.lineno + 1
                if span > FUNCTION_LINE_LIMIT:
                    result.setdefault(relative, set()).add(node.name)
    return result


def test_no_new_functions_exceed_size_limit() -> None:
    """No function may exceed 80 lines unless it is in the frozen baseline.

    As WP-D decomposes each offender, remove its entry from
    ``_FUNCTION_SIZE_BASELINE`` so the net tightens and regression is caught.
    """
    current = _functions_exceeding_limit()

    new_offenders: dict[str, set[str]] = {}
    for module, names in current.items():
        allowed = _FUNCTION_SIZE_BASELINE.get(module, set())
        fresh = names - allowed
        if fresh:
            new_offenders[module] = fresh

    assert not new_offenders, (
        f"New functions exceeding {FUNCTION_LINE_LIMIT} lines detected "
        f"(baseline has {_sum_baseline()} entries). "
        f"Either decompose them to <= {FUNCTION_LINE_LIMIT} lines or, "
        f"if intentional, add them to _FUNCTION_SIZE_BASELINE:\n"
        f"{new_offenders}"
    )


def _sum_baseline() -> int:
    return sum(len(names) for names in _FUNCTION_SIZE_BASELINE.values())
