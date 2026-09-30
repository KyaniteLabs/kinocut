"""Reproduce the runtime source allocation audit; this measures source, not CPU cost."""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
import tokenize
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CATEGORIES = ("deterministic", "prose_llm", "traditional_ml")
TEXT_OVERRIDES: dict[str, str] = {}
# Audited functions which implement or invoke learned inference/clustering.
# Their surrounding validation, adapters and registrations remain deterministic.
ML_FUNCTIONS = {
    "kinocut/image_engine.py": {"extract_colors"},
    "kinocut/ai_engine/transcribe.py": {"ai_transcribe"},
    "kinocut/ai_engine/_longform_runtime.py": {"_transcribe_chunk"},
    "kinocut/ai_engine/stem.py": {"_run_demucs_separation"},
    "kinocut/ai_engine/upscale.py": {
        "_init_opencv_sr",
        "_init_realesrgan",
        "_ai_upscale_opencv",
        "_upscale_with_realesrgan",
    },
    "kinocut/object_matte/runtime.py": {"make_session"},
    "kinocut/object_matte/infer.py": {"infer_mask"},
    "kinocut/aesthetic/__init__.py": {"__init__", "score_frame", "score_frames", "score_pil"},
    "kinocut/audio_engine/integrations/basic_pitch_bridge.py": {"detect_pitch", "audio_to_midi"},
    "kinocut_sound/public/asr_worker.py": {"recognize"},
}
SOURCE_EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".sh", ".html", ".css", ".glsl"}
RUNTIME_PREFIXES = ("kinocut/", "kinocut_sound/", "npm/", "mcpb/server/", "compat/mcp-video-shim/")


def runtime(path: str) -> bool:
    return path == "mcp_video.py" or path.startswith(RUNTIME_PREFIXES)


def tool_functions() -> tuple[set[tuple[str, str]], set[str]]:
    from kinocut.server import mcp

    functions = {
        (str(Path(inspect.getsourcefile(inspect.unwrap(t.fn))).relative_to(ROOT)), t.fn.__name__)
        for t in mcp._tool_manager._tools.values()
    }
    descriptions = {mcp.instructions}

    def schema_descriptions(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "description" and isinstance(item, str):
                    descriptions.add(item)
                else:
                    schema_descriptions(item)
        elif isinstance(value, list):
            for item in value:
                schema_descriptions(item)

    for tool in mcp._tool_manager._tools.values():
        schema_descriptions(tool.parameters)
    for resource in [*mcp._resource_manager._resources.values(), *mcp._resource_manager._templates.values()]:
        if resource.description:
            descriptions.add(resource.description)
    return functions, descriptions


def contains(node: ast.AST, start: tuple[int, int], end: tuple[int, int]) -> bool:
    return (node.lineno, node.col_offset) <= start and end <= (node.end_lineno, node.end_col_offset)


def python_units(path: str, tools: set[tuple[str, str]], descriptions: set[str]) -> tuple[Counter, list[dict]]:
    source = TEXT_OVERRIDES.get(path)
    if source is None:
        source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    spans: list[tuple[ast.AST, str]] = []
    classified = []
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                category = (
                    "prose_llm"
                    if ((path, getattr(node, "name", "")) in tools or body[0].value.value in descriptions)
                    else "excluded"
                )
                spans.append((body[0], category))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in ML_FUNCTIONS.get(path, set()):
            spans.append((node, "traditional_ml"))
            found.add(node.name)
            classified.append({"path": path, "function": node.name, "start": node.lineno, "end": node.end_lineno})
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and path == "kinocut/image_engine.py"
            and node.value.startswith("Describe this product image")
        ):
            spans.append((node, "prose_llm"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in descriptions:
            spans.append((node, "prose_llm"))
    missing = ML_FUNCTIONS.get(path, set()) - found
    if missing:
        raise ValueError(f"Audit manifest stale for {path}: {sorted(missing)}")
    # Most specific spans win: exclude ordinary docstrings inside model functions.
    spans.sort(key=lambda s: (s[0].end_lineno - s[0].lineno, s[0].end_col_offset - s[0].col_offset))
    counts = Counter({category: 0 for category in CATEGORIES})
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in ignored:
            continue
        category = next((kind for node, kind in spans if contains(node, token.start, token.end)), "deterministic")
        if category != "excluded":
            counts[category] += len(token.string.encode("utf-8"))
    return counts, classified


def other_units(path: str) -> Counter:
    # The small JS/TS/shell runtime has no model calls; use the same byte unit,
    # dropping whitespace and whole comment lines (inline comments remain).
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    text = "".join("".join(line.split()) for line in lines if not line.lstrip().startswith(("//", "#", "/*", "*")))
    return Counter({"deterministic": len(text.encode("utf-8"))})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--baseline-head",
        action="store_true",
        help="Read dirty tracked source files from HEAD; MCP metadata must be unchanged.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tracked_paths = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, timeout=15).splitlines()
    paths = tracked_paths
    if not args.baseline_head:
        # Newly implemented runtime modules count before they are committed.
        paths = sorted(
            set(
                subprocess.check_output(
                    ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                    cwd=ROOT,
                    text=True,
                    timeout=15,
                ).splitlines()
            )
        )
    tools, descriptions = tool_functions()
    if args.baseline_head:
        changed = subprocess.check_output(
            ["git", "diff", "HEAD", "--name-only"], cwd=ROOT, text=True, timeout=15
        ).splitlines()
        for path in changed:
            if runtime(path) and Path(path).suffix in SOURCE_EXTENSIONS:
                TEXT_OVERRIDES[path] = subprocess.check_output(
                    ["git", "show", f"HEAD:{path}"], cwd=ROOT, text=True, timeout=15
                )
    total = Counter({category: 0 for category in CATEGORIES})
    rows, classified, inventory = [], [], []
    for path in paths:
        extension = Path(path).suffix
        role = "runtime_source" if runtime(path) and extension in SOURCE_EXTENSIONS else "support_or_data"
        size = len(TEXT_OVERRIDES[path].encode("utf-8")) if path in TEXT_OVERRIDES else (ROOT / path).stat().st_size
        inventory.append({"path": path, "role": role, "bytes": size})
        if role != "runtime_source":
            continue
        if extension == ".py":
            counts, functions = python_units(path, tools, descriptions)
            classified.extend(functions)
        else:
            counts = other_units(path)
        total.update(counts)
        rows.append({"path": path, **{c: counts[c] for c in CATEGORIES}})
    host_prose = sum((ROOT / p).stat().st_size for p in paths if p.startswith("skills/") and p.endswith("SKILL.md"))
    denominator = sum(total.values())
    percent = {c: round(total[c] / denominator * 100, 4) for c in CATEGORIES}
    percent["deterministic"] = round(100 - percent["prose_llm"] - percent["traditional_ml"], 4)
    summary = {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=15).strip(),
        "unit": "UTF-8 source-token bytes (Python); non-whitespace code bytes (other languages)",
        "source_state": "HEAD; dirty tracked source read from Git" if args.baseline_head else "working tree",
        "runtime_files": len(rows),
        "tracked_files_inventoried": len(tracked_paths),
        "inventoried_files": len(inventory),
        "inventory_scope": "tracked HEAD paths"
        if args.baseline_head
        else "tracked and unignored new working-tree paths",
        "registered_mcp_functions": len(tools),
        "totals": dict(total),
        "denominator": denominator,
        "percent": percent,
        "rounding": "Deterministic share absorbs the rounding residual so displayed percentages sum to 100%.",
        "host_skill_prose_bytes_separate": host_prose,
        "ml_function_manifest": classified,
        "limits": [
            "Static authored-source allocation, not runtime time, cost, invocation frequency or a quality score.",
            "Model function bodies include their local orchestration; preprocessing outside those functions remains code.",
            "Operational MCP tool/resource descriptions, schema descriptions, server instructions and the direct LLM prompt count as prose; ordinary docstrings/comments excluded.",
            "External models, FFmpeg, libraries, generated bundles, manifests and example assets excluded.",
            "Host skills are reported separately; creation templates target external generative media, not an in-process LLM.",
        ],
    }
    (args.output / "allocation.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for name, data in (("runtime-allocation.csv", rows), ("repository-inventory.csv", inventory)):
        with (args.output / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    print(
        json.dumps(
            {k: summary[k] for k in ("runtime_files", "tracked_files_inventoried", "totals", "percent")}, indent=2
        )
    )


if __name__ == "__main__":
    main()
