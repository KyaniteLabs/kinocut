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
