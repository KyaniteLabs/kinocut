"""Digest-keyed publication of trusted external renderer outputs."""

import hashlib
import itertools
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from graphlib import TopologicalSorter
from pathlib import Path

from ..bounded_process import run_bounded
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffmpeg
from ..host_probes import cached_sha256_file
from ..publication import anchored_tree, validate_artifact_location
from .concat import splice_shots_lossless, verify_concat_compatibility


@dataclass(frozen=True)
class ShotSpec:
    shot_id: str
    command: tuple[str, ...] | None = None
    source_path: str | Path | None = None
    start_frame: int = 0
    frame_count: int = 1
    warmup_frames: int = 0
    params: dict = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.shot_id or not (self.command or self.source_path):
            raise ValueError("Shot needs an ID and a command or source")
        if self.frame_count < 1 or min(self.start_frame, self.warmup_frames) < 0:
            raise ValueError("Invalid shot frame range")


def _json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compute_shot_digest(shot: ShotSpec, upstream_digests=None) -> str:
    deps = upstream_digests or {}
    payload = dict(
        version=1,
        shot_id=shot.shot_id,
        command=shot.command,
        params=shot.params,
        start=shot.start_frame,
        count=shot.frame_count,
        warmup=shot.warmup_frames,
        source=cached_sha256_file(Path(shot.source_path)) if shot.source_path else None,
        dependencies=[(name, deps[name]) for name in shot.dependencies],
    )
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def _matches(entry, digest):
    clip = entry / "clip.mp4"
    metadata = entry / "metadata.json"
    if entry.is_symlink() or clip.is_symlink() or metadata.is_symlink():
        return False
    try:
        record = json.loads(metadata.read_text(encoding="utf-8"))
        return record == {"digest": digest, "clip_sha256": cached_sha256_file(clip)}
    except (OSError, ValueError):
        return False


def _produce(shot, output, upstream):
    if not shot.command:
        end = shot.start_frame + shot.frame_count
        trim = f"trim=start_frame={shot.start_frame}:end_frame={end},setpts=PTS-STARTPTS"
        _run_ffmpeg(
            [
                "-v",
                "error",
                "-i",
                str(shot.source_path),
                "-map",
                "0:v:0",
                "-vf",
                trim,
                "-an",
                "-c:v",
                "libx264",
                "-qp",
                "0",
                str(output),
            ]
        )
        return
    tokens = {
        "{output}": str(output),
        "{source}": str(shot.source_path or ""),
        "{params}": _json(shot.params),
        "{start_frame}": str(shot.start_frame),
        "{frame_count}": str(shot.frame_count),
        "{warmup_frames}": str(shot.warmup_frames),
        **{"{dep:" + name + "}": str(path) for name, path in upstream.items()},
    }
    if "{output}" not in shot.command:
        raise ValueError("Renderer command must include an {output} argument")
    result = run_bounded([tokens.get(arg, arg) for arg in shot.command], timeout=86400)
    if result.returncode:
        raise MCPVideoError("Shot renderer exited unsuccessfully", code="shot_renderer_failed")


def _build(shot, cache, digest, upstream):
    entry = cache / digest
    if not entry.is_symlink() and _matches(entry / "media", digest):
        return False
    with anchored_tree(entry, overwrite=entry.exists()) as stage:
        stage = stage / "media"
        stage.mkdir()
        clip = stage / "clip.mp4"
        _produce(shot, clip, upstream)
        verify_concat_compatibility([clip], [shot.frame_count])
        record = {"digest": digest, "clip_sha256": cached_sha256_file(clip)}
        (stage / "metadata.json").write_text(_json(record), encoding="utf-8")
    return True


def _pin_worker(enabled, slots):
    if enabled and hasattr(os, "sched_setaffinity"):
        try:
            cpus = sorted(os.sched_getaffinity(0))
            os.sched_setaffinity(0, {cpus[next(slots) % len(cpus)]})
        except (OSError, NotImplementedError):
            pass


def render_shot_plan(shots, output_path, cache_dir, *, max_workers=4, pin_cpus=False):
    shots = tuple(shots)
    by_id = {shot.shot_id: shot for shot in shots}
    if not shots or len(by_id) != len(shots):
        raise ValueError("Provide a nonempty plan with unique shot IDs")
    graph = TopologicalSorter()
    for shot in shots:
        if set(shot.dependencies) - by_id.keys():
            raise ValueError("Shot references an unknown dependency")
        graph.add(shot.shot_id, *shot.dependencies)
    graph.prepare()
    cache = Path(validate_artifact_location(str(cache_dir), "Shot cache"))
    cache.mkdir(parents=True, exist_ok=True)
    digests, clips, changed = {}, {}, {}
    with ThreadPoolExecutor(max_workers, initializer=_pin_worker, initargs=(pin_cpus, itertools.count())) as pool:
        while graph.is_active():
            jobs = {}
            for name in graph.get_ready():
                shot = by_id[name]
                digest = digests[name] = compute_shot_digest(shot, digests)
                upstream = {dep: clips[dep] for dep in shot.dependencies}
                jobs[name] = pool.submit(_build, shot, cache, digest, upstream)
                clips[name] = cache / digest / "media" / "clip.mp4"
            for name, job in jobs.items():
                changed[name] = job.result()
                graph.done(name)
    total = splice_shots_lossless([clips[name] for name in by_id], output_path, [shot.frame_count for shot in shots])
    return dict(
        rebuilt=[name for name in by_id if changed[name]],
        reused=[name for name in by_id if not changed[name]],
        digests=digests,
        total_frames=total,
        output_path=str(output_path),
    )
