"""Guarded local Revideo bridge backed by Kinocut's pinned template."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .defaults import (
    DEFAULT_FFMPEG_TIMEOUT,
    DEFAULT_REVIDEO_FPS,
    DEFAULT_REVIDEO_FRAMES,
    DEFAULT_REVIDEO_HEIGHT,
    DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    DEFAULT_REVIDEO_OUT_FILE,
    DEFAULT_REVIDEO_RENDER_TIMEOUT,
    DEFAULT_REVIDEO_SEED,
    DEFAULT_REVIDEO_WIDTH,
    DEFAULT_REVIDEO_WORKERS,
)
from .errors import (
    MCPVideoError,
    RevideoNotFoundError,
    RevideoProjectError,
    RevideoRenderError,
    ValidationError,
)
from .ffmpeg_helpers import _atomic_output, _run_command, _run_ffprobe_json, _validate_write_path
from .limits import (
    DOCTOR_COMMAND_TIMEOUT,
    MAX_REVIDEO_JOB_JSON_BYTES,
    REVIDEO_NODE_MAJOR_MIN,
    REVIDEO_TIMEOUT_MAX_SECONDS,
)
from .revideo_models import RevideoRenderResult
from .validation import (
    REVIDEO_FPS_MAX,
    REVIDEO_FPS_MIN,
    REVIDEO_FPS_TOLERANCE,
    REVIDEO_FRAMES_MAX,
    REVIDEO_FRAMES_MIN,
    REVIDEO_HEIGHT_MAX,
    REVIDEO_HEIGHT_MIN,
    REVIDEO_MEDIA_IDENTITIES,
    REVIDEO_OUT_FILE_SUFFIXES,
    REVIDEO_DURATION_TOLERANCE_FRAMES,
    REVIDEO_SEED_MAX,
    REVIDEO_SEED_MIN,
    REVIDEO_WIDTH_MAX,
    REVIDEO_WIDTH_MIN,
    REVIDEO_WORKERS_MAX,
    REVIDEO_WORKERS_MIN,
)

TEMPLATE_DIR = Path(__file__).parent / "revideo_template"
_CONTROL_FILES = ("package.json", "package-lock.json", "render.mjs", "tsconfig.json", "src/project.ts")
_SCENE_NAME_RE = re.compile(r"""makeScene2D\(\s*['"]""")
_BARE_MAKESCENE_RE = re.compile(r"makeScene2D\(\s*(?:async\s+)?function")
_RUN_OUTPUT_ENV = "KINOCUT_REVIDEO_OUTPUT_FILE"
_PRIVATE_NAME_ATTEMPTS = 8
_PROBE_INTEGER_MAX = 2**63 - 1
logger = logging.getLogger(__name__)


def _require_revideo_deps() -> None:
    """Require Node.js and npm at the bridge's supported floor."""
    node = shutil.which("node")
    if node is None:
        raise RevideoNotFoundError("node not found on PATH")
    if shutil.which("npm") is None:
        raise RevideoNotFoundError("npm not found on PATH")
    try:
        probe = subprocess.run(  # noqa: S603
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=DOCTOR_COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RevideoNotFoundError(f"node --version failed to run ({type(exc).__name__})") from exc
    if probe.returncode != 0:
        raise RevideoNotFoundError("node --version returned a non-zero exit")
    match = re.match(r"v(\d+)", (probe.stdout or "").strip())
    if match is None:
        raise RevideoNotFoundError("could not parse `node --version` output")
    try:
        major = int(match.group(1))
    except ValueError as exc:
        raise RevideoNotFoundError("could not parse `node --version` output") from exc
    if major < REVIDEO_NODE_MAJOR_MIN:
        raise RevideoNotFoundError(f"node v{major} found on PATH but Node.js {REVIDEO_NODE_MAJOR_MIN}+ is required")


def _finite_number(value: Any, name: str, *, allow_text: bool = False) -> float:
    if isinstance(value, bool) or (not allow_text and not isinstance(value, (int, float))):
        raise ValueError(name)
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(name) from exc
    if not math.isfinite(number):
        raise ValueError(name)
    return number


def _validate_timeout(value: Any, name: str) -> None:
    try:
        number = _finite_number(value, name)
    except ValueError:
        raise ValidationError(name, "must be a positive finite number") from None
    if number <= 0 or number > REVIDEO_TIMEOUT_MAX_SECONDS:
        raise ValidationError(name, f"must be in (0, {REVIDEO_TIMEOUT_MAX_SECONDS}]")


def _validate_job(job: Any) -> dict[str, Any]:
    """Validate and normalize a bridge job spec against repository bounds."""
    if not isinstance(job, dict):
        raise ValidationError("job", "must be an object")

    def _int_field(name: str, lo: int, hi: int, default: int) -> int:
        raw = job.get(name, default)
        if not isinstance(raw, int) or isinstance(raw, bool) or not lo <= raw <= hi:
            raise ValidationError(f"job.{name}", f"must be an int in [{lo}, {hi}] (got {raw!r})")
        return raw

    def _float_field(name: str, lo: float, hi: float, default: float) -> float:
        raw = job.get(name, default)
        try:
            number = _finite_number(raw, name)
        except ValueError:
            number = math.nan
        if not lo <= number <= hi:
            raise ValidationError(f"job.{name}", f"must be a number in [{lo}, {hi}] (got {raw!r})")
        return number

    normalized: dict[str, Any] = {
        "width": _int_field("width", REVIDEO_WIDTH_MIN, REVIDEO_WIDTH_MAX, DEFAULT_REVIDEO_WIDTH),
        "height": _int_field("height", REVIDEO_HEIGHT_MIN, REVIDEO_HEIGHT_MAX, DEFAULT_REVIDEO_HEIGHT),
        "fps": _float_field("fps", REVIDEO_FPS_MIN, REVIDEO_FPS_MAX, DEFAULT_REVIDEO_FPS),
        "frames": _int_field("frames", REVIDEO_FRAMES_MIN, REVIDEO_FRAMES_MAX, DEFAULT_REVIDEO_FRAMES),
        "workers": _int_field("workers", REVIDEO_WORKERS_MIN, REVIDEO_WORKERS_MAX, DEFAULT_REVIDEO_WORKERS),
        "seed": _int_field("seed", REVIDEO_SEED_MIN, REVIDEO_SEED_MAX, DEFAULT_REVIDEO_SEED),
    }
    out_file = job.get("out_file", DEFAULT_REVIDEO_OUT_FILE)
    if (
        not isinstance(out_file, str)
        or not out_file.endswith(REVIDEO_OUT_FILE_SUFFIXES)
        or "/" in out_file
        or "\\" in out_file
        or Path(out_file).name != out_file
    ):
        raise ValidationError(
            "job.out_file",
            f"must be a bare filename ending with one of {REVIDEO_OUT_FILE_SUFFIXES} (got {out_file!r})",
        )
    normalized["out_file"] = out_file
    return normalized


def _read_scene_source(scene_source: str | Path | None) -> bytes | None:
    if scene_source is None:
        return None
    source = Path(scene_source)
    try:
        if source.is_symlink() or not source.is_file():
            raise RevideoProjectError(str(source), "scene source must be a regular non-symlink file")
        scene_bytes = source.read_bytes()
        scene_text = scene_bytes.decode("utf-8")
    except RevideoProjectError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RevideoProjectError(str(source), f"scene source could not be read ({type(exc).__name__})") from exc
    if not scene_bytes:
        raise RevideoProjectError(str(source), "scene source is missing or empty")
    if _BARE_MAKESCENE_RE.search(scene_text) and not _SCENE_NAME_RE.search(scene_text):
        raise RevideoProjectError(
            str(source),
            "makeScene2D requires the scene name as its FIRST argument — "
            "makeScene2D('myScene', function* (view) {...})",
        )
    return scene_bytes


def _validate_materialize_destination(dest: Path) -> None:
    try:
        if dest.is_symlink():
            raise RevideoProjectError(str(dest), "destination must not be a symlink")
        if dest.exists() and not dest.is_dir():
            raise RevideoProjectError(str(dest), "destination exists and is not a directory")
        if dest.exists() and any(dest.iterdir()):
            raise RevideoProjectError(str(dest), "destination exists and is not empty")
    except RevideoProjectError:
        raise
    except OSError as exc:
        raise RevideoProjectError(str(dest), f"destination could not be inspected ({type(exc).__name__})") from exc


def materialize_project(dest: str | Path, job: dict[str, Any], scene_source: str | Path | None = None) -> Path:
    """Materialize a complete bridge project without exposing partial files."""
    normalized_job = _validate_job(job)
    materialized_job = {**job, **normalized_job}
    try:
        job_bytes = (json.dumps(materialized_job, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("job", "must contain JSON-serializable values") from exc
    if len(job_bytes) > MAX_REVIDEO_JOB_JSON_BYTES:
        raise ValidationError("job", f"must not exceed {MAX_REVIDEO_JOB_JSON_BYTES} encoded bytes")
    scene_bytes = _read_scene_source(scene_source)
    dest_path = Path(dest)
    _validate_materialize_destination(dest_path)
    replace_empty = dest_path.exists()
    stage: Path | None = None
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".kinocut_revideo_", dir=dest_path.parent))
        shutil.copytree(
            TEMPLATE_DIR,
            stage,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("node_modules", "out", "dist"),
        )
        if scene_bytes is not None:
            (stage / "src" / "scene.ts").write_bytes(scene_bytes)
        (stage / "src" / "job.json").write_bytes(job_bytes)
        if replace_empty:
            dest_path.rmdir()
        os.replace(stage, dest_path)
        stage = None
    except OSError as exc:
        if replace_empty and not dest_path.exists():
            with contextlib.suppress(OSError):
                dest_path.mkdir(exist_ok=True)
        raise RevideoProjectError(str(dest_path), f"project could not be materialized ({type(exc).__name__})") from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
    return dest_path


def _regular_file_below(project: Path, relative: str) -> Path:
    current = project
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise RevideoProjectError(str(current), "project paths must not contain symlinks")
    if not current.is_file():
        raise RevideoProjectError(str(current), "required regular file is missing")
    return current


def _read_materialized_job(project: Path) -> tuple[dict[str, Any], str]:
    path = _regular_file_below(project, "src/job.json")
    try:
        with path.open("rb") as handle:
            job_bytes = handle.read(MAX_REVIDEO_JOB_JSON_BYTES + 1)
        if len(job_bytes) > MAX_REVIDEO_JOB_JSON_BYTES:
            raise RevideoProjectError(str(path), "job file exceeds the 1 MiB limit")
        raw = json.loads(job_bytes.decode("utf-8"))
        return _validate_job(raw), hashlib.sha256(job_bytes).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise RevideoProjectError(str(path), f"job file is invalid ({type(exc).__name__})") from exc


def _validate_materialized_project(project_dir: str | Path) -> tuple[Path, dict[str, Any], str]:
    requested = Path(project_dir)
    try:
        if requested.is_symlink():
            raise RevideoProjectError(str(requested), "project root must not be a symlink")
        project = requested.resolve()
        if not project.is_dir():
            raise RevideoProjectError(str(requested), "not a materialized bridge project")
        for relative in _CONTROL_FILES:
            actual = _regular_file_below(project, relative)
            expected = TEMPLATE_DIR / relative
            if actual.read_bytes() != expected.read_bytes():
                raise RevideoProjectError(str(actual), "control file does not match the Kinocut template")
        _regular_file_below(project, "src/scene.ts")
        job, job_sha256 = _read_materialized_job(project)
        return project, job, job_sha256
    except RevideoProjectError:
        raise
    except OSError as exc:
        raise RevideoProjectError(str(requested), f"project could not be validated ({type(exc).__name__})") from exc


def _run_npm(
    args: list[str],
    cwd: Path,
    timeout: int | float,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run npm with closed stdin and a hard timeout."""
    cmd = ["npm", *args]
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **(extra_env or {})},
        )
    except subprocess.TimeoutExpired:
        raise RevideoRenderError(" ".join(cmd), -1, "npm step timed out") from None
    except FileNotFoundError:
        raise RevideoNotFoundError("npm command not found") from None
    except OSError as exc:
        raise RevideoRenderError(" ".join(cmd), -1, f"npm command could not start ({type(exc).__name__})") from exc


def install_deps(project_dir: str | Path, timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT) -> None:
    """Install the materialized bridge's pinned dependencies via npm ci."""
    _validate_timeout(timeout, "timeout")
    project, _job, _job_sha256 = _validate_materialized_project(project_dir)
    _require_revideo_deps()
    _install_validated(project, timeout)


def _install_validated(project: Path, timeout: int | float) -> None:
    result = _run_npm(["ci", "--no-audit", "--no-fund"], project, timeout)
    if result.returncode != 0:
        raise RevideoRenderError("npm ci", result.returncode, result.stderr)


def _checked_path(path: Path, label: str, *, directory: bool, allow_absent: bool) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if allow_absent:
            return False
        raise RevideoProjectError(str(path), f"{label} is missing") from None
    except OSError as exc:
        raise RevideoProjectError(str(path), f"{label} could not be inspected ({type(exc).__name__})") from exc
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        raise RevideoProjectError(str(path), f"{label} must not be a symlink")
    if not expected:
        kind = "directory" if directory else "regular file"
        raise RevideoProjectError(str(path), f"{label} must be a {kind}")
    return True


def _private_output_leaf(out_dir: Path, suffix: str, purpose: str) -> Path:
    for _attempt in range(_PRIVATE_NAME_ATTEMPTS):
        name = f".kinocut-{purpose}-{secrets.token_hex(12)}{suffix}"
        if Path(name).name != name or not name.endswith(REVIDEO_OUT_FILE_SUFFIXES):
            raise RevideoRenderError("prepare Revideo output", -1, "generated output name was invalid")
        path = out_dir / name
        if not _checked_path(path, f"private {purpose} leaf", directory=False, allow_absent=True):
            return path
    raise RevideoRenderError("prepare Revideo output", -1, f"could not allocate a private {purpose} name")


def _prepare_output_paths(project: Path, job: dict[str, Any]) -> tuple[Path, Path]:
    out_dir = project / "out"
    if not _checked_path(out_dir, "project output path", directory=True, allow_absent=True):
        try:
            out_dir.mkdir()
        except OSError as exc:
            raise RevideoProjectError(
                str(out_dir), f"output directory could not be created ({type(exc).__name__})"
            ) from exc
        _checked_path(out_dir, "project output path", directory=True, allow_absent=False)
    canonical = out_dir / job["out_file"]
    _checked_path(canonical, "canonical project output", directory=False, allow_absent=True)
    return canonical, _private_output_leaf(out_dir, Path(job["out_file"]).suffix, "run")


def _fresh_candidate(path: Path, returncode: int) -> Path:
    try:
        _checked_path(path, "fresh render output", directory=False, allow_absent=False)
        if os.lstat(path).st_size <= 0:
            raise RevideoRenderError("npm run render", returncode, "render reported no fresh output")
    except RevideoRenderError:
        raise
    except (OSError, RevideoProjectError) as exc:
        raise RevideoRenderError("npm run render", returncode, "render reported no fresh output") from exc
    return path


def _positive_integer(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(name)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        number = int(value)
    else:
        raise ValueError(name)
    if not 0 < number <= maximum:
        raise ValueError(name)
    return number


def _parse_fps(value: Any) -> float:
    numerator, separator, denominator = str(value).partition("/")
    if not separator:
        fps = _finite_number(numerator, "fps", allow_text=True)
        if fps <= 0:
            raise ValueError("fps")
        return fps
    num = _positive_integer(numerator, "fps numerator", _PROBE_INTEGER_MAX)
    den = _positive_integer(denominator, "fps denominator", _PROBE_INTEGER_MAX)
    return num / den


def _validate_render_identity(job: dict[str, Any], probe: Mapping[str, Any], stream: Mapping[str, Any]) -> None:
    suffix = Path(job["out_file"]).suffix
    expected = REVIDEO_MEDIA_IDENTITIES[suffix]
    format_data = probe.get("format")
    if not isinstance(format_data, Mapping):
        raise RevideoRenderError("verify Revideo output", 0, "render output format metadata is missing")
    format_name = format_data.get("format_name")
    if not isinstance(format_name, str) or expected["format_token"] not in {
        token.lower() for token in format_name.split(",")
    }:
        raise RevideoRenderError("verify Revideo output", 0, f"render output format does not match {suffix}")
    codec_name = stream.get("codec_name")
    if not isinstance(codec_name, str) or codec_name not in expected["video_codecs"]:
        raise RevideoRenderError("verify Revideo output", 0, f"render output codec does not match {suffix}")
    if "major_brand" in expected:
        tags = format_data.get("tags")
        brand = tags.get("major_brand") if isinstance(tags, Mapping) else None
        if not isinstance(brand, str) or brand != expected["major_brand"]:
            raise RevideoRenderError("verify Revideo output", 0, f"render output major brand does not match {suffix}")
    if "profile" in expected:
        profile = stream.get("profile")
        if not isinstance(profile, str) or profile != expected["profile"]:
            raise RevideoRenderError("verify Revideo output", 0, f"render output profile does not match {suffix}")


def _inspect_render(
    candidate: Path, project: Path, job: dict[str, Any], job_sha256: str, started: float
) -> RevideoRenderResult:
    try:
        probe = _run_ffprobe_json(str(candidate), count_frames=True)
        streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "video"]
        if not streams:
            raise RevideoRenderError("verify Revideo output", 0, "render output has no video stream")
        stream = streams[0]
        _validate_render_identity(job, probe, stream)
        width = _positive_integer(stream.get("width"), "width", REVIDEO_WIDTH_MAX)
        height = _positive_integer(stream.get("height"), "height", REVIDEO_HEIGHT_MAX)
        fps = _parse_fps(stream.get("avg_frame_rate"))
        frames = _positive_integer(stream.get("nb_read_frames"), "frame count", REVIDEO_FRAMES_MAX)
        duration = _finite_number(probe.get("format", {}).get("duration"), "duration", allow_text=True)
        if duration <= 0:
            raise ValueError("duration")
        _validate_observed_media(job, width, height, fps, frames, duration)
        _run_command(
            ["ffmpeg", "-v", "error", "-xerror", "-i", str(candidate), "-f", "null", "-"],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
        digest = _sha256_file(candidate)
    except RevideoRenderError:
        raise
    except (AttributeError, MCPVideoError, OSError, OverflowError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise RevideoRenderError(
            "verify Revideo output", 0, f"render output validation failed ({type(exc).__name__})"
        ) from exc
    return RevideoRenderResult(
        project_dir=str(project),
        output_path="",
        output_sha256=digest,
        job_sha256=job_sha256,
        width=width,
        height=height,
        fps=fps,
        frames=frames,
        duration_seconds=duration,
        render_seconds=round(time.monotonic() - started, 3),
    )


def _validate_observed_media(
    job: dict[str, Any], width: int, height: int, fps: float, frames: int, duration: float
) -> None:
    if width != job["width"]:
        raise RevideoRenderError("verify Revideo output", 0, "render output width does not match the job")
    if height != job["height"]:
        raise RevideoRenderError("verify Revideo output", 0, "render output height does not match the job")
    if abs(fps - job["fps"]) > REVIDEO_FPS_TOLERANCE:
        raise RevideoRenderError("verify Revideo output", 0, "render output frame rate does not match the job")
    if frames != job["frames"]:
        raise RevideoRenderError("verify Revideo output", 0, "render output frame count does not match the job")
    expected_duration = job["frames"] / job["fps"]
    tolerance = REVIDEO_DURATION_TOLERANCE_FRAMES / job["fps"]
    if abs(duration - expected_duration) > tolerance:
        raise RevideoRenderError("verify Revideo output", 0, "render output duration does not match the job")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_digest(path: Path, expected_sha256: str, label: str) -> None:
    try:
        if _sha256_file(path) != expected_sha256:
            raise RevideoRenderError(label, -1, "copied render bytes failed SHA-256 verification")
    except RevideoRenderError:
        raise
    except OSError as exc:
        raise RevideoRenderError(
            label, -1, f"copied render bytes could not be verified ({type(exc).__name__})"
        ) from exc


def _cleanup_owned_path(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Could not inspect %s during Revideo cleanup: %s", label, type(exc).__name__)
        return
    try:
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        logger.warning("Could not remove %s during Revideo cleanup: %s", label, type(exc).__name__)


def _restore_canonical(canonical: Path, backup: Path | None, existed: bool) -> None:
    try:
        if os.path.lexists(canonical):
            _cleanup_owned_path(canonical, "replacement canonical output")
        if existed:
            if backup is None:
                raise OSError("canonical backup was not created")
            os.replace(backup, canonical)
    except OSError as exc:
        raise RevideoRenderError(
            "restore Revideo output", -1, f"canonical output restoration failed ({type(exc).__name__})"
        ) from exc


def _install_canonical(candidate: Path, canonical: Path, existed: bool, expected_sha256: str) -> Path | None:
    suffix = canonical.suffix
    stage = _private_output_leaf(canonical.parent, suffix, "stage")
    backup = _private_output_leaf(canonical.parent, suffix, "backup") if existed else None
    moved_old = False
    try:
        shutil.copyfile(candidate, stage)
        _checked_path(stage, "canonical staging output", directory=False, allow_absent=False)
        _require_digest(stage, expected_sha256, "verify Revideo project output")
        if existed and backup is not None:
            os.replace(canonical, backup)
            moved_old = True
        os.replace(stage, canonical)
    except RevideoRenderError:
        _cleanup_owned_path(stage, "canonical staging output")
        if moved_old:
            _restore_canonical(canonical, backup, True)
        raise
    except (OSError, RevideoProjectError) as exc:
        _cleanup_owned_path(stage, "canonical staging output")
        if moved_old:
            _restore_canonical(canonical, backup, True)
        raise RevideoRenderError(
            "publish Revideo project output", -1, f"project output publication failed ({type(exc).__name__})"
        ) from exc
    return backup


def _publish_external(canonical: Path, output_path: str, expected_sha256: str) -> None:
    try:
        with _atomic_output(output_path) as stage_name:
            stage = Path(stage_name)
            shutil.copyfile(canonical, stage)
            _require_digest(stage, expected_sha256, "verify Revideo final output")
    except OSError as exc:
        raise RevideoRenderError(
            "publish Revideo output", -1, f"output publication failed ({type(exc).__name__})"
        ) from exc


def _render_transaction(
    project: Path,
    job: dict[str, Any],
    output_path: str,
    timeout: int | float,
    canonical: Path,
    run_candidate: Path,
    job_sha256: str,
) -> RevideoRenderResult:
    started = time.monotonic()
    canonical_existed = os.path.lexists(canonical)
    backup: Path | None = None
    try:
        result = _run_npm(["run", "render"], project, timeout, extra_env={_RUN_OUTPUT_ENV: run_candidate.name})
        if result.returncode != 0:
            raise RevideoRenderError("npm run render", result.returncode, result.stderr)
        candidate = _fresh_candidate(run_candidate, result.returncode)
        _current_job, current_sha256 = _read_materialized_job(project)
        if current_sha256 != job_sha256:
            raise RevideoProjectError(str(project / "src" / "job.json"), "job changed during render")
        receipt = _inspect_render(candidate, project, job, job_sha256, started)
        backup = _install_canonical(candidate, canonical, canonical_existed, receipt.output_sha256)
        try:
            _publish_external(canonical, output_path, receipt.output_sha256)
        except BaseException:
            restore_backup = backup
            backup = None
            _restore_canonical(canonical, restore_backup, canonical_existed)
            raise
        return receipt.model_copy(update={"output_path": str(Path(output_path))})
    finally:
        _cleanup_owned_path(run_candidate, "per-run output")
        if backup is not None:
            _cleanup_owned_path(backup, "canonical backup")


def _render_validated(
    project: Path,
    job: dict[str, Any],
    output_path: str,
    timeout: int | float,
    job_sha256: str,
    *,
    require_deps: bool,
) -> RevideoRenderResult:
    _validate_output_selection(job, output_path)
    canonical, run_candidate = _prepare_output_paths(project, job)
    if require_deps:
        _require_revideo_deps()
    return _render_transaction(project, job, output_path, timeout, canonical, run_candidate, job_sha256)


def _validate_output_selection(job: dict[str, Any], output_path: str) -> None:
    _validate_write_path(
        output_path,
        allowed_existing_suffixes=frozenset(REVIDEO_OUT_FILE_SUFFIXES),
        label="revideo output_path",
    )
    if Path(output_path).suffix.lower() != Path(job["out_file"]).suffix.lower():
        raise ValidationError("output_path", "suffix must match job.out_file")


def render(
    project_dir: str | Path,
    output_path: str,
    timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> RevideoRenderResult:
    """Render an exact materialized project and atomically publish verified bytes."""
    _validate_timeout(timeout, "timeout")
    project, job, job_sha256 = _validate_materialized_project(project_dir)
    return _render_validated(project, job, output_path, timeout, job_sha256, require_deps=True)


def render_job(
    job: dict[str, Any],
    output_path: str,
    work_dir: str | Path | None = None,
    scene_source: str | Path | None = None,
    install_timeout: int = DEFAULT_REVIDEO_INSTALL_TIMEOUT,
    render_timeout: int = DEFAULT_REVIDEO_RENDER_TIMEOUT,
) -> RevideoRenderResult:
    """Materialize, install, locally render, and verify one Revideo job."""
    _validate_timeout(install_timeout, "install_timeout")
    _validate_timeout(render_timeout, "render_timeout")
    normalized_job = _validate_job(job)
    _validate_output_selection(normalized_job, output_path)
    _require_revideo_deps()
    root = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="kinocut-revideo-"))
    project = materialize_project(root / "bridge", job, scene_source=scene_source)
    _install_validated(project, install_timeout)
    project, normalized_job, job_sha256 = _validate_materialized_project(project)
    return _render_validated(project, normalized_job, output_path, render_timeout, job_sha256, require_deps=False)
