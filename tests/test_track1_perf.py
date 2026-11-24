"""Cold import boundaries and avoided work, independent of machine speed."""

import importlib
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.name != "posix", reason="Windows uses a job handle")
@pytest.mark.parametrize("retaining", [True, False])
def test_wait_notified_without_sleep_polling(retaining, monkeypatch):
    from kinocut import process_observation, process_tree

    if not retaining and not process_observation.supports_nonreaping_wait():
        pytest.skip("Native WNOWAIT unavailable")
    monkeypatch.setattr(process_observation, "supports_nonreaping_wait", lambda: not retaining)
    monkeypatch.setattr(process_tree, "time", SimpleNamespace(monotonic=time.monotonic))
    reader, writer = os.pipe()
    command = [sys.executable, "-c", f"import os; os.read({reader},1); raise SystemExit(3)"]
    tree = process_tree.ProcessTree(command, pass_fds=(reader,))
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            tree.wait(timeout=0.001)
        os.write(writer, b"x")
        assert tree.wait(timeout=5) == 3
        assert tree.process.returncode is None
    finally:
        tree.close()
        tree.process.stdout.close()
        tree.process.stderr.close()
        os.close(reader)
        os.close(writer)


def test_cold_import_boundaries():
    script = """
import sys
import kinocut.workflow._versions
assert 'kinocut.engine' not in sys.modules
from kinocut.server import mcp
from kinocut.tool_registry import TOOL_NAMES_BY_MODULE, TOOL_REGISTRY, configure_tool_surface
from kinocut.server_tools_families import list_operations, FAMILY_MODULES
def loaded():
    return {mod for mod in TOOL_NAMES_BY_MODULE if 'kinocut.' + mod in sys.modules}
editor = loaded()
assert editor == {mod for mod, names in TOOL_NAMES_BY_MODULE.items()
                  if any({'core','editor'}.intersection(TOOL_REGISTRY[name]) for name in names)}
items = list_operations(family='image_ops')
assert items['success'] and items['operations'] and all(row['family']=='image_ops' for row in items['operations'])
assert loaded() == editor | set(FAMILY_MODULES['image_ops'])
configure_tool_surface('all')
assert editor < loaded() == set(TOOL_NAMES_BY_MODULE)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "KINOCUT_TOOLS": "profile:editor"},
    )
    assert result.returncode == 0, result.stderr


def test_add_audio_reads_each_input_once(sample_video, sample_audio_wav, tmp_path, monkeypatch):
    from kinocut import engine_probe, engine_audio_ops

    reads = []
    probe = engine_probe._run_ffprobe_json

    def counted(path):
        reads.append(path)
        return probe(path)

    monkeypatch.setattr(engine_probe, "_run_ffprobe_json", counted)
    monkeypatch.setattr(
        "kinocut.engine_media_timeline._packet_extent", lambda *_: pytest.fail("unexpected packet scan")
    )
    engine_audio_ops.add_audio(sample_video, sample_audio_wav, output_path=str(tmp_path / "attached.mp4"))
    assert reads.count(sample_video) == reads.count(sample_audio_wav) == 1


@pytest.mark.parametrize("suffix", ["jpg", "png"])
def test_thumbnail_publishes_winning_candidate(sample_video, tmp_path, monkeypatch, suffix):
    from kinocut import aesthetic, engine_thumbnail
    from kinocut.aesthetic import smart_thumbnail

    frames = []

    def extract(args):
        frames.append(Path(args[-1]))
        frames[-1].write_bytes(str(len(frames)).encode())

    class Scorer:
        def score_frames(self, paths):
            return [0, 8, *([1] * (len(paths) - 2))]

    monkeypatch.setattr(smart_thumbnail, "_get_video_duration", lambda _: 120)
    monkeypatch.setattr(smart_thumbnail, "_run_ffmpeg", extract)
    monkeypatch.setattr(aesthetic, "is_available", lambda: True)
    monkeypatch.setattr(aesthetic.NimaScorer, "get", lambda: Scorer())
    monkeypatch.setattr(engine_thumbnail, "_run_ffmpeg", lambda _: pytest.fail("winner extracted twice"))
    output = tmp_path / f"frame.{suffix}"
    engine_thumbnail.thumbnail(sample_video, output_path=str(output))
    assert output.read_bytes() == b"2" and len(frames) == 8
    assert all(path.suffix == f".{suffix}" and not path.exists() for path in frames)


@pytest.mark.parametrize(
    "engine,operation,params",
    [
        ("resize", "resize", {"width": 64}),
        ("rotate", "rotate", {"angle": 90}),
        ("stabilize", "stabilize", {}),
        ("overlay", "overlay_video", {}),
    ],
)
def test_video_transforms_request_audio_copy(engine, operation, params, sample_video, tmp_path, monkeypatch):
    module = importlib.import_module(f"kinocut.engine_{engine}")
    commands = []

    def capture(args):
        commands.append(args)
        raise RuntimeError("captured command")

    monkeypatch.setattr(module, "_run_ffmpeg", capture)
    if engine in {"stabilize", "overlay"}:
        monkeypatch.setattr(module, "_require_filter", lambda *_: None)
    if engine == "stabilize":
        monkeypatch.setattr(module, "_detect_motion_vectors", lambda *_: None)
    inputs = [sample_video] * (2 if engine == "overlay" else 1)
    with pytest.raises(RuntimeError, match="captured command"):
        getattr(module, operation)(*inputs, **params, output_path=str(tmp_path / "out.mp4"))
    assert commands[0][commands[0].index("-c:a") + 1] == "copy"


@pytest.mark.parametrize(
    "audio_codec,out_ext",
    [
        ("pcm_mulaw", ".mp4"),
        ("libopus", ".mov"),
        ("flac", ".mov"),
        ("libopus", ".avi"),
    ],
)
def test_incompatible_audio_falls_back_to_aac(sample_video, tmp_path, audio_codec, out_ext):
    from kinocut.engine_probe import probe
    from kinocut.engine_resize import resize

    source = str(tmp_path / f"{audio_codec}.mkv")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", sample_video, "-c:v", "copy", "-c:a", audio_codec, source], check=True
    )
    output = resize(source, width=64, output_path=str(tmp_path / f"out{out_ext}"))
    assert probe(output.output_path).audio_codec == "aac"


def test_video_only_muxer_failure_does_not_retry_or_mask_error(tmp_path, monkeypatch):
    from kinocut import engine_resize
    from kinocut.errors import ProcessingError

    video_only = tmp_path / "video_only.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=64x64:r=25:d=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video_only),
        ],
        check=True,
    )
    calls = 0
    real_run = engine_resize._run_ffmpeg

    def counted_run(args, *rest):
        nonlocal calls
        calls += 1
        return real_run(args, *rest)

    monkeypatch.setattr(engine_resize, "_run_ffmpeg", counted_run)
    with pytest.raises(ProcessingError) as exc_info:
        engine_resize.resize(str(video_only), width=32, output_path=str(tmp_path / "bad.webm"))
    assert calls == 1
    assert exc_info.value.code != "unsupported_codec"


def test_stream_cut_mp4_edit_list_trims_audio_to_picture_end(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from kinocut import engine_media_timeline
    from kinocut.engine_audio_mix import _picture_timeline
    from kinocut.engine_audio_ops import add_audio
    from kinocut.engine_probe import _run_ffprobe_json

    src = tmp_path / "src.mp4"
    cut = tmp_path / "cut.mp4"
    wav = tmp_path / "long.wav"
    out = tmp_path / "trimmed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=64x64:r=25:d=6",
            "-c:v",
            "libx264",
            "-g",
            "25",
            "-bf",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.24", "-i", str(src), "-t", "4", "-c", "copy", str(cut)],
        check=True,
    )
    # Confirm cut fixture has matching format/video duration and start_time so only edit-list detection triggers scan.
    cut_meta = _run_ffprobe_json(str(cut))
    scan = Mock(wraps=engine_media_timeline._packet_extent)
    monkeypatch.setattr(engine_media_timeline, "_packet_extent", scan)
    assert _picture_timeline(str(src), _run_ffprobe_json(str(src))) == (0, 6)
    scan.assert_not_called()
    assert _picture_timeline(str(cut), cut_meta)[1] > 0
    scan.assert_called_once_with(str(cut), "v:0")
    cut_vs = next(s for s in cut_meta["streams"] if s["codec_type"] == "video")
    assert abs(float(cut_vs["duration"]) - float(cut_meta["format"]["duration"])) <= 0.001
    assert abs(float(cut_vs["start_time"]) - float(cut_meta["format"]["start_time"])) <= 0.001
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=8", str(wav)],
        check=True,
    )
    add_audio(str(cut), str(wav), output_path=str(out), duration_policy="trim_audio")
    meta = _run_ffprobe_json(str(out))
    v_dur = float(next(s for s in meta["streams"] if s["codec_type"] == "video")["duration"])
    a_dur = float(next(s for s in meta["streams"] if s["codec_type"] == "audio")["duration"])
    assert abs(a_dur - v_dur) <= 0.05


@pytest.mark.skipif(os.name != "posix", reason="POSIX FD limit test")
def test_retaining_wait_handles_high_numbered_fd(monkeypatch):
    import fcntl
    import resource
    from kinocut import process_observation, process_tree

    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft <= 1050:
        pytest.skip("RLIMIT_NOFILE too small for high-FD test")
    monkeypatch.setattr(process_observation, "supports_nonreaping_wait", lambda: False)
    real_dup = os.dup

    def high_dup(fd: int) -> int:
        return fcntl.fcntl(fd, fcntl.F_DUPFD, 1030)

    monkeypatch.setattr(process_tree.os, "dup", high_dup)
    reader, writer = os.pipe()
    command = [sys.executable, "-c", f"import os; os.read({reader},1); raise SystemExit(7)"]
    tree = process_tree.ProcessTree(command, pass_fds=(reader,))
    try:
        os.write(writer, b"x")
        assert tree.wait(timeout=5) == 7
    finally:
        monkeypatch.setattr(process_tree.os, "dup", real_dup)
        tree.close()
        tree.process.stdout.close()
        tree.process.stderr.close()
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize("flow", ["shorts", "timeline"])
def test_only_deliverable_gets_faststart(sample_video, tmp_path, monkeypatch, flow):
    from kinocut.publication import _staging as staged_writers
    from kinocut.engine_timeline import edit_timeline
    from kinocut.product.shorts_flow import video_shorts

    commands = []
    original = staged_writers.staged_ffmpeg_command

    def record(cmd, *args):
        if cmd[-1].endswith(".mp4"):
            commands.append((Path(cmd[-1]).parent, "+faststart" in cmd))
        return original(cmd, *args)

    monkeypatch.setattr(staged_writers, "staged_ffmpeg_command", record)
    output = str(tmp_path / "published.mp4")
    if flow == "shorts":
        assert video_shorts(sample_video, [(0, 0.2, "caption")], output_path=output)["success"]
    else:
        edit_timeline(
            {
                "width": 64,
                "height": 64,
                "tracks": [{"type": "video", "clips": [{"source": sample_video, "duration": 0.2}]}],
            },
            output,
        )
    assert len(commands) >= 3
    assert commands[-1] == (tmp_path.resolve(), True)
    assert not any(faststart for _, faststart in commands[:-1])
