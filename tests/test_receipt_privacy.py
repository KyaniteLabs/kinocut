"""Receipt/artifact privacy scan (plan §5c/§7/§8).

Fails if any committed public surface, or any freshly produced workflow dry-run/render
artifact, leaks an absolute home path, the running user's name, or a secret-shaped token.
Workflow receipts and plan artifacts must carry workspace-relative paths only.
"""

from __future__ import annotations

import getpass
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Home-dir path prefixes, built by concatenation so this test file never self-matches.
_HOME_PREFIXES = ("/" + "Users/", "/" + "home/")

# Secret-shaped tokens (targeted prefixes). sha256: hashes in receipts are integrity
# checks, not secrets, so a bare hex run is intentionally NOT flagged.
_SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def _committed_surfaces() -> list[Path]:
    """Every committed public surface a receipt/example/doc leak could hide in."""
    paths: list[Path] = []
    paths.extend((ROOT / "docs").rglob("*.md"))
    paths.extend((ROOT / "docs").rglob("*.json"))
    paths.extend((ROOT / "examples").rglob("*.json"))
    paths.extend((ROOT / "examples").rglob("*.md"))
    paths.extend([ROOT / "README.md", ROOT / "llms.txt", ROOT / "skills" / "mcp-video" / "SKILL.md"])
    return sorted({p for p in paths if p.exists()})


def _scan(text: str) -> list[str]:
    """Return the privacy offenders found in ``text`` (empty when clean)."""
    hits: list[str] = []
    for prefix in _HOME_PREFIXES:
        # Require a real path character after the prefix so prose/ellipsis mentions are safe.
        if re.search(re.escape(prefix) + r"[A-Za-z0-9._-]", text):
            hits.append(prefix)
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(match.group(0)[:12] + "...")
    return hits


def _leaks(text: str, workspace: Path) -> list[str]:
    """Offenders in a produced artifact: home paths, tokens, workspace abs path, username."""
    hits = _scan(text)
    if str(workspace) in text:
        hits.append("workspace-abs-path")
    user = getpass.getuser()
    if user and len(user) >= 3 and user in text:
        hits.append("username")
    return hits


def _linear_spec() -> dict:
    return {
        "schema_version": 1,
        "name": "captioned-vertical-short",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {"id": "trim-hero", "op": "trim", "inputs": {"src": "@sources.hero"},
             "params": {"start": 0, "duration": 1}, "output": "@work/hero_trim.mp4"},
            {"id": "caption", "op": "add_text", "inputs": {"src": "@work/hero_trim.mp4"},
             "params": {"text": "Watch this"}, "output": "@outputs.master"},
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }


def _workspace(tmp_path: Path, sample_video: str) -> Path:
    ws = tmp_path / "job-ws"
    (ws / "input").mkdir(parents=True)
    shutil.copy(sample_video, ws / "input" / "hero.mp4")
    (ws / "job.json").write_text(json.dumps(_linear_spec()), encoding="utf-8")
    return ws


def test_committed_public_surfaces_are_privacy_clean():
    """Docs, SKILL, README, llms, and committed example specs/receipts carry no home
    paths, usernames-in-paths, or secret-shaped tokens."""
    offenders = {
        str(path.relative_to(ROOT)): hits
        for path in _committed_surfaces()
        if (hits := _scan(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"privacy leak in committed surfaces: {offenders}"


def test_workflow_plan_artifact_stays_workspace_relative(tmp_path, sample_video):
    """A representative dry-run plan leaks neither the workspace path nor a home path."""
    from mcp_video.workflow import plan_workflow, validate_workflow_spec

    ws = _workspace(tmp_path, sample_video)
    spec_path = str(ws / "job.json")
    validate_workflow_spec(spec_path)  # must not raise
    plan = plan_workflow(spec_path, save_plan=str(ws / "plan.json"))

    assert _leaks(json.dumps(plan), ws) == []
    assert _leaks((ws / "plan.json").read_text(encoding="utf-8"), ws) == []


def test_workflow_render_receipt_stays_workspace_relative(tmp_path, sample_video):
    """A real render receipt (returned dict and saved file) stays workspace-relative."""
    from mcp_video.workflow import render_workflow

    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(str(ws / "job.json"), save_receipt=str(ws / "receipt.json"))

    assert receipt["status"] == "completed"
    assert _leaks(json.dumps(receipt), ws) == []
    assert _leaks((ws / "receipt.json").read_text(encoding="utf-8"), ws) == []


def test_composite_layer_plan_stays_workspace_relative(tmp_path, sample_video):
    """A composite-layers dry-run layer_plan records workspace-relative paths only.

    The receipt's ``output_path`` (and ``resolved_src``) must be emitted relative to the
    spec directory when the file lives inside it, never as an absolute home path.
    """
    from mcp_video.engine_composite_layers import composite_layers

    ws = tmp_path / "composite-ws"
    (ws / "input").mkdir(parents=True)
    shutil.copy(sample_video, ws / "input" / "hero.mp4")
    spec = {
        "canvas": {"width": 320, "height": 240, "fps": 12, "duration": 1},
        "layers": [{"id": "base", "type": "video", "src": "input/hero.mp4"}],
        "output": {"path": "output/composite.mp4"},
    }
    (ws / "job.json").write_text(json.dumps(spec), encoding="utf-8")

    result = composite_layers(str(ws / "job.json"), save_layer_plan=str(ws / "plan.json"), dry_run=True)

    assert result.layer_plan["output_path"] == "output/composite.mp4"
    assert result.layer_plan["layers"][0]["resolved_src"] == "input/hero.mp4"
    assert _leaks(json.dumps(result.layer_plan), ws) == []
    assert _leaks((ws / "plan.json").read_text(encoding="utf-8"), ws) == []
