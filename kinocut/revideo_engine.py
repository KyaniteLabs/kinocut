"""Revideo bridge engine (Sinter x Kino integration, liminal #999).

Renders programmatic frame-sequenced video through the vendored, lockfile-
pinned Revideo template at ``kinocut/revideo_template``: materialize a
per-job copy, write ``src/job.json``, optionally swap in an artwork scene,
then drive ``npm ci && npm run render`` under timeouts with a closed stdin,
and ffprobe-verify the output. Determinism is the contract — the same job
and scene must produce byte-identical output (verified 2026-08-31).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .defaults import (
    DEFAULT_REVIDEO_FPS,
    DEFAULT_REVIDEO_FRAMES,
    DEFAULT_REVIDEO_HEIGHT,
    DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    DEFAULT_REVIDEO_RENDER_TIMEOUT,
    DEFAULT_REVIDEO_WIDTH,
    DEFAULT_REVIDEO_WORKERS,
)
from .errors import (
    RevideoNotFoundError,
    RevideoProjectError,
    RevideoRenderError,
    ValidationError,
)
from .ffmpeg_helpers import _run_ffprobe_json, _validate_write_path
from .revideo_models import RevideoRenderResult
from .validation import (
    REVIDEO_FPS_MAX,
    REVIDEO_FPS_MIN,
    REVIDEO_FRAMES_MAX,
    REVIDEO_OUT_FILE_SUFFIXES,
    REVIDEO_SEED_MAX,
    REVIDEO_SEED_MIN,
    REVIDEO_FRAMES_MIN,
    REVIDEO_HEIGHT_MAX,
    REVIDEO_HEIGHT_MIN,
    REVIDEO_WIDTH_MAX,
    REVIDEO_WIDTH_MIN,
    REVIDEO_WORKERS_MAX,
    REVIDEO_WORKERS_MIN,
)

TEMPLATE_DIR = Path(__file__).parent / "revideo_template"

# Scene sources must pass this guard: makeScene2D requires the scene NAME as
# its first argument (an upstream skeleton shipped without it and failed at
# render time with "Cannot read properties of undefined (reading 'name')").
_SCENE_NAME_RE = re.compile(r"makeScene2D\(\s*['\"]")
_BARE_MAKESCENE_RE = re.compile(r"makeScene2D\(\s*(?:async\s+)?function")


def _require_revideo_deps() -> None:
    """Raise a helpful error if Node.js/npm are not available."""
    if shutil.which("node") is None:
        raise RevideoNotFoundError("node not found on PATH")
    if shutil.which("npm") is None:
        raise RevideoNotFoundError("npm not found on PATH")


def _validate_job(job: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a bridge job spec against repo bounds."""

    def _int_field(name: str, lo: int, hi: int, default: int) -> int:
        raw = job.get(name, default)
        if not isinstance(raw, int) or isinstance(raw, bool) or not lo <= raw <= hi:
            raise ValidationError(f"job.{name}", f"must be an int in [{lo}, {hi}] (got {raw!r})")
        return raw

    def _float_field(name: str, lo: float, hi: float, default: float) -> float:
        raw = job.get(name, default)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not lo <= float(raw) <= hi:
            raise ValidationError(f"job.{name}", f"must be a number in [{lo}, {hi}] (got {raw!r})")
        return float(raw)

    normalized: dict[str, Any] = {
        "width": _int_field("width", REVIDEO_WIDTH_MIN, REVIDEO_WIDTH_MAX, DEFAULT_REVIDEO_WIDTH),
        "height": _int_field("height", REVIDEO_HEIGHT_MIN, REVIDEO_HEIGHT_MAX, DEFAULT_REVIDEO_HEIGHT),
        "fps": _float_field("fps", REVIDEO_FPS_MIN, REVIDEO_FPS_MAX, DEFAULT_REVIDEO_FPS),
        "frames": _int_field("frames", REVIDEO_FRAMES_MIN, REVIDEO_FRAMES_MAX, DEFAULT_REVIDEO_FRAMES),
        "workers": _int_field("workers", REVIDEO_WORKERS_MIN, REVIDEO_WORKERS_MAX, DEFAULT_REVIDEO_WORKERS),
        "seed": _int_field("seed", REVIDEO_SEED_MIN, REVIDEO_SEED_MAX, 1),
    }
    out_file = job.get("out_file", "video.mp4")
    if (
        not isinstance(out_file, str)
        or not out_file.endswith(REVIDEO_OUT_FILE_SUFFIXES)
        or "/" in out_file
        or "\\" in out_file
        or Path(out_file).name != out_file
    ):
        # Bare filename only: the pinned renderer writes AND unlinks along
        # outDir/outFile paths, so any path separator here would be an
        # arbitrary write/unlink primitive. Separators are checked explicitly
        # because Path.name does not split backslashes on POSIX.
        raise ValidationError(
            "job.out_file",
            f"must be a bare filename ending with one of {REVIDEO_OUT_FILE_SUFFIXES} (got {out_file!r})",
        )
    normalized["out_file"] = out_file
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_project(
    dest: str | Path,
    job: dict[str, Any],
    scene_source: str | Path | None = None,
) -> Path:
    """Copy the vendored bridge template to ``dest`` and write the job spec.

    ``scene_source`` optionally replaces ``src/scene.ts`` with an artwork
    adapter scene; it must call ``makeScene2D('<name>', function* ...)``.
    """
    normalized_job = _validate_job(job)
    dest_path = Path(dest)
    if dest_path.exists() and any(dest_path.iterdir()):
        raise RevideoProjectError(str(dest_path), "destination exists and is not empty")
    dest_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        TEMPLATE_DIR,
        dest_path,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", "out", "dist"),
    )

    scene_path = dest_path / "src" / "scene.ts"
    if scene_source is not None:
        source = Path(scene_source)
        if not source.is_file() or source.stat().st_size == 0:
            raise RevideoProjectError(str(scene_source), "scene source is missing or empty")
        scene_text = source.read_text(encoding="utf-8")
        if _BARE_MAKESCENE_RE.search(scene_text) and not _SCENE_NAME_RE.search(scene_text):
            raise RevideoProjectError(
                str(scene_source),
                "makeScene2D requires the scene name as its FIRST argument — "
                "makeScene2D('myScene', function* (view) {...})",
            )
        shutil.copyfile(source, scene_path)

    job_path = dest_path / "src" / "job.json"
    job_path.write_text(json.dumps(normalized_job, indent=2) + "\n", encoding="utf-8")
    return dest_path


def _run_npm(
    args: list[str],
    cwd: Path,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run npm with a closed stdin and a hard timeout."""
    cmd = ["npm", *args]
    # The full environment is inherited on purpose: the bridge template's
    # render.mjs reads KINOCUT_REVIDEO_EXECUTABLE_PATH from it.
    env = {**os.environ}
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RevideoRenderError(" ".join(cmd), -1, "npm step timed out") from None
    except FileNotFoundError:
        raise RevideoNotFoundError("npm command not found") from None


def install_deps(
    project_dir: str | Path,
    timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
) -> None:
    """Install the bridge template's pinned dependencies via ``npm ci``."""
    result = _run_npm(["ci", "--no-audit", "--no-fund"], Path(project_dir), timeout)
    if result.returncode != 0:
        raise RevideoRenderError("npm ci", result.returncode, result.stderr)


def render(
    project_dir: str | Path,
    output_path: str,
    timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> RevideoRenderResult:
    """Render the materialized project and move the output to ``output_path``."""
    project = Path(project_dir)
    if not (project / "package.json").is_file():
        raise RevideoProjectError(str(project), "not a materialized bridge project (missing package.json)")
    _validate_write_path(
        output_path,
        allowed_existing_suffixes=frozenset(REVIDEO_OUT_FILE_SUFFIXES),
        label="revideo output_path",
    )

    started = time.monotonic()
    result = _run_npm(["run", "render"], project, timeout)
    if result.returncode != 0:
        raise RevideoRenderError("npm run render", result.returncode, result.stderr)

    rendered_line = next(
        (line.strip() for line in reversed((result.stdout or "").splitlines()) if line.strip()),
        "",
    )
    job_spec = json.loads((project / "src" / "job.json").read_text(encoding="utf-8"))
    candidate = Path(rendered_line) if rendered_line else None
    if candidate is None or not candidate.is_file():
        candidate = project / "out" / job_spec.get("out_file", "video.mp4")
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise RevideoRenderError("npm run render", result.returncode, "render reported no output file")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if candidate.resolve() != output.resolve():
        shutil.move(str(candidate), str(output))

    probe = _run_ffprobe_json(str(output))
    streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise RevideoRenderError("npm run render", 0, "output has no video stream")
    stream = streams[0]
    num, _, den = str(stream.get("avg_frame_rate", "0/1")).partition("/")
    try:
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    except ValueError:
        fps = 0.0
    return RevideoRenderResult(
        project_dir=str(project),
        output_path=str(output),
        output_sha256=_sha256_file(output),
        width=int(stream.get("width", 0)),
        height=int(stream.get("height", 0)),
        fps=round(fps, 3),
        frames=int(job_spec.get("frames", 0)),
        duration_seconds=float(probe.get("format", {}).get("duration", 0.0)),
        render_seconds=round(time.monotonic() - started, 3),
    )


def render_job(
    job: dict[str, Any],
    output_path: str,
    work_dir: str | Path | None = None,
    scene_source: str | Path | None = None,
    install_timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    render_timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> RevideoRenderResult:
    """Full pipeline: deps check, materialize, install, render, verify.

    The work dir (and its node_modules copy) is deliberately kept — receipts
    and re-renders reference the project dir — and is the caller's to clean
    up once the result is accepted.
    """
    _require_revideo_deps()
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="kinocut-revideo-")
    project = materialize_project(Path(work_dir) / "bridge", job, scene_source=scene_source)
    install_deps(project, timeout=install_timeout)
    return render(project, output_path, timeout=render_timeout)
