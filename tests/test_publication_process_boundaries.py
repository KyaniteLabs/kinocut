"""Observable attacks and process failures at shared publication boundaries."""

import os
import shutil
import subprocess
import sys
import tracemalloc
from contextvars import copy_context
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_output, _reset_operation_inputs, _validate_input_path
from kinocut.ffmpeg_progress import run_progress
from kinocut.limits import FFMPEG_PROGRESS_STDERR_BYTES


@pytest.mark.skipif(os.name != "posix" or not shutil.which("ffmpeg"), reason="POSIX real FFmpeg")
@pytest.mark.parametrize("runner", ["_run_ffmpeg", "_run_command", "_run_ffmpeg_with_progress"])
def test_writer_leaf_swap_does_not_overwrite_source(tmp_path, runner):
    from kinocut import ffmpeg_helpers as helpers

    source = tmp_path / "source.mp4"
    source.write_bytes(b"recorded input must survive")
    helpers._validate_input_path(str(source))
    final = tmp_path / "delivery.wav"
    final.write_bytes(b"prior delivery")
    with pytest.raises(MCPVideoError), helpers._atomic_output(str(final)) as stage:
        os.unlink(stage)
        os.symlink(source, stage)
        args = ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.1", "-c:a", "pcm_s16le", stage]
        if runner == "_run_command":
            helpers._run_command(["ffmpeg", "-y", *args])
        elif runner == "_run_ffmpeg_with_progress":
            helpers._run_ffmpeg_with_progress(args, 0.1, lambda percent: None)
        else:
            helpers._run_ffmpeg(args)
    assert source.read_bytes() == b"recorded input must survive"
    assert final.read_bytes() == b"prior delivery"
    assert Path(stage).is_symlink()


@pytest.mark.skipif(os.name != "posix" or not shutil.which("ffmpeg"), reason="POSIX real FFmpeg")
@pytest.mark.parametrize("suffix,signature", [(".png", b"\x89PNG"), (".jpg", b"\xff\xd8"), (".mp4", b"ftyp")])
def test_descriptor_output_keeps_codec_and_seekable_container(tmp_path, suffix, signature):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    final = tmp_path / ("delivery" + suffix)
    with _atomic_output(str(final)) as stage:
        args = ["-f", "lavfi", "-i", "color=blue:s=32x32:d=0.1", "-frames:v", "1"]
        if suffix == ".mp4":
            args.extend(["-c:v", "mpeg4", "-movflags", "+faststart"])
        _run_ffmpeg([*args, stage])
    assert signature in final.read_bytes()[:32]


@pytest.mark.skipif(os.name != "posix" or not shutil.which("ffmpeg"), reason="POSIX real FFmpeg")
@pytest.mark.parametrize("selector", ["-c:0", "-codec:0", "-c:V", "-c:i:0", "-codec:#0"])
def test_descriptor_output_respects_explicit_stream_codec(tmp_path, selector):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    final = tmp_path / "explicit.png"
    with _atomic_output(str(final)) as stage:
        _run_ffmpeg(["-f", "lavfi", "-i", "color=blue:s=32x32:d=0.1", "-frames:v", "1", selector, "mjpeg", stage])
    assert final.read_bytes().startswith(b"\xff\xd8")


@pytest.mark.skipif(os.name != "posix" or not shutil.which("ffmpeg"), reason="POSIX real FFmpeg")
def test_explicit_nonimage_muxer_keeps_its_default_codec(tmp_path):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    final = tmp_path / "explicit.png"
    with _atomic_output(str(final)) as stage:
        _run_ffmpeg(["-f", "lavfi", "-i", "color=blue:s=32x32:d=0.1", "-frames:v", "1", "-f", "gif", stage])
    assert final.read_bytes().startswith(b"GIF")


@pytest.mark.skipif(os.name != "posix" or not shutil.which("ffmpeg"), reason="POSIX real FFmpeg")
def test_inferred_single_image_output_still_rejects_multiple_frames(tmp_path):
    from kinocut.errors import ProcessingError
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    final = tmp_path / "image.png"
    final.write_bytes(b"prior image")
    with pytest.raises(ProcessingError), _atomic_output(str(final)) as stage:
        _run_ffmpeg(["-f", "lavfi", "-i", "color=blue:s=32x32:r=2:d=1", stage])
    assert final.read_bytes() == b"prior image"


@pytest.mark.skipif(os.name == "nt", reason="Windows held stage denies filename replacement")
def test_bound_artifact_writer_ignores_replaced_filename(tmp_path):
    from kinocut.ffmpeg_helpers import _atomic_artifact, _open_staged_writer

    source = tmp_path / "source.json"
    source.write_bytes(b"preserved source")
    with pytest.raises(MCPVideoError), _atomic_artifact(str(tmp_path / "receipt.json")) as stage:
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(b"unowned replacement")
        os.replace(replacement, stage)
        with _open_staged_writer(stage) as stream:
            stream.write(b"owned receipt")
    assert source.read_bytes() == b"preserved source"
    assert Path(stage).read_bytes() == b"unowned replacement"


@pytest.mark.parametrize("writer", ["ffmpeg", "artifact"])
def test_copied_context_cannot_reuse_closed_stage_descriptor(tmp_path, writer):
    from kinocut import staged_writers
    from kinocut.ffmpeg_helpers import _open_staged_writer, _run_ffmpeg

    with _atomic_output(str(tmp_path / "output.wav")) as stage:
        captured = copy_context()
        stage_fd = staged_writers._STAGES.get()[os.path.abspath(stage)].fd
    victim = tmp_path / "victim.wav"
    victim.write_bytes(b"preserved source")
    descriptor = os.open(victim, os.O_RDWR)
    try:
        os.dup2(descriptor, stage_fd)

        def attempted_write():
            if writer == "artifact":
                with _open_staged_writer(stage) as stream:
                    stream.write(b"corruption")
            else:
                _run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=0.1", stage])

        with pytest.raises(MCPVideoError, match="transaction has ended"):
            captured.run(attempted_write)
    finally:
        os.close(descriptor)
        if stage_fd != descriptor:
            os.close(stage_fd)
    assert victim.read_bytes() == b"preserved source"


def test_outstanding_writer_prevents_premature_publication(tmp_path):
    from kinocut.ffmpeg_helpers import _open_staged_writer

    final = tmp_path / "output.wav"
    final.write_bytes(b"prior delivery")
    writer = None
    try:
        with pytest.raises(MCPVideoError, match="still active"), _atomic_output(str(final)) as stage:
            writer = _open_staged_writer(stage)
            stream = writer.__enter__()
            stream.write(b"unfinished output")
        assert final.read_bytes() == b"prior delivery"
    finally:
        if writer is not None:
            writer.__exit__(None, None, None)


@pytest.fixture(autouse=True)
def isolated_paths():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def test_prospective_output_validation_does_not_hide_later_input(tmp_path):
    from kinocut.ffmpeg_helpers import _validate_output_path

    source = tmp_path / "source.mp4"
    source.write_bytes(b"preserved")
    _validate_output_path(str(source))
    _validate_input_path(str(source))
    with pytest.raises(MCPVideoError, match="aliases an input"):
        _validate_output_path(str(source))
    assert source.read_bytes() == b"preserved"


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="Real FFprobe needed")
def test_owned_artifact_probe_does_not_require_ffmpeg(tmp_path, monkeypatch):
    from kinocut import engine_runtime_utils as runtime
    from kinocut.errors import FFmpegNotFoundError
    from kinocut.ffmpeg_helpers import _atomic_artifact, _open_staged_writer, _run_command

    def unavailable():
        raise FFmpegNotFoundError()

    with _atomic_artifact(str(tmp_path / "receipt.json")) as stage:
        with _open_staged_writer(stage) as stream:
            stream.write(b"{}")
        monkeypatch.setattr(runtime, "_ffmpeg", unavailable)
        # FFprobe -version is successful regardless of the extra registered file.
        result = _run_command(["ffprobe", "-version", stage])
        assert result.returncode == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX parent rename attack")
def test_parent_swap_never_publishes_into_recorded_input_or_deletes_unowned_stage(tmp_path):
    safe, victim = tmp_path / "safe", tmp_path / "victim"
    safe.mkdir()
    victim.mkdir()
    source = victim / "out.mp4"
    source.write_bytes(b"original source")
    _validate_input_path(str(source))
    moved = tmp_path / "moved"
    with pytest.raises(MCPVideoError, match="directory changed"), _atomic_output(str(safe / "out.mp4")) as staged:
        with open(staged, "wb") as handle:
            handle.write(b"real staged output")
        safe.rename(moved)
        safe.symlink_to(victim, target_is_directory=True)
        planted = victim / os.path.basename(staged)
        planted.write_bytes(b"unowned replacement")
    assert source.read_bytes() == b"original source"
    assert planted.read_bytes() == b"unowned replacement"
    assert not (moved / os.path.basename(staged)).exists()


def test_owned_stage_can_be_probed_before_publish(tmp_path):
    final = tmp_path / "out.mp4"
    with _atomic_output(str(final)) as staged:
        with open(staged, "wb") as handle:
            handle.write(b"staged")
        _validate_input_path(staged)
    assert final.read_bytes() == b"staged"


@pytest.mark.skipif(os.name == "nt", reason="Windows held stage denies filename replacement")
def test_staging_regular_inode_replacement_is_not_published_or_deleted(tmp_path):
    final = tmp_path / "out.mp4"
    final.write_bytes(b"prior delivery")
    with pytest.raises(MCPVideoError, match="staging file changed"), _atomic_output(str(final)) as staged:
        replacement = tmp_path / "attacker.mp4"
        replacement.write_bytes(b"replacement")
        os.replace(replacement, staged)
    assert final.read_bytes() == b"prior delivery"
    assert Path(staged).read_bytes() == b"replacement"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows staging handle sharing")
def test_windows_stage_replacement_is_blocked_and_artifact_publishes(tmp_path):
    from kinocut.ffmpeg_helpers import _atomic_artifact, _open_staged_writer

    final = tmp_path / "receipt.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"unowned")
    with _atomic_artifact(str(final)) as stage:
        with pytest.raises(OSError):
            os.replace(replacement, stage)
        with pytest.raises(OSError):
            os.unlink(stage)
        with _open_staged_writer(stage) as writer:
            writer.write(b'{"published":true}')
    assert final.read_bytes() == b'{"published":true}'
    assert replacement.read_bytes() == b"unowned"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("ffmpeg"), reason="Native Windows real FFmpeg")
def test_windows_staged_ffmpeg_produces_nonempty_delivery(tmp_path):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    final = tmp_path / "delivery.wav"
    with _atomic_output(str(final)) as stage:
        _run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=0.1", "-c:a", "pcm_s16le", stage])
    assert final.read_bytes().startswith(b"RIFF")
    assert final.stat().st_size > 44


def test_destination_hardlink_swap_cannot_replace_an_input(tmp_path):
    source, final = tmp_path / "source.mp4", tmp_path / "out.mp4"
    source.write_bytes(b"original")
    _validate_input_path(str(source))
    with pytest.raises(MCPVideoError, match="aliases an input"), _atomic_output(str(final)) as staged:
        with open(staged, "wb") as handle:
            handle.write(b"rendered")
        os.link(source, final)
    assert source.read_bytes() == final.read_bytes() == b"original"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows directory-handle sharing")
def test_windows_parent_cannot_be_renamed_while_publication_is_open(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    with _atomic_output(str(safe / "out.mp4")) as staged:
        with pytest.raises(OSError):
            safe.rename(tmp_path / "moved")
        with open(staged, "wb") as handle:
            handle.write(b"output")
    assert (safe / "out.mp4").read_bytes() == b"output"


def test_caller_interrupt_kills_and_reaps_actual_progress_process(monkeypatch):
    real_popen, processes = subprocess.Popen, []

    def spawn(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        processes.append(proc)
        return proc

    from kinocut.process_tree import ProcessTree

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(
        ProcessTree, "wait", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt("caller cancelled"))
    )
    with pytest.raises(KeyboardInterrupt, match="caller cancelled"):
        run_progress([sys.executable, "-c", "import time; time.sleep(60)"], 60, lambda _: None, float)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stderr.closed


def test_no_newline_diagnostics_have_bounded_parent_memory_and_still_report_progress():
    from kinocut.ffmpeg_helpers import _parse_ffmpeg_time

    values = []
    script = "import sys; sys.stderr.buffer.write(b'x'*2000000+b' time=00:00:00.50\\r'); sys.stderr.flush()"
    tracemalloc.start()
    try:
        result = run_progress([sys.executable, "-c", script], 1, values.append, _parse_ffmpeg_time)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000
    assert len(result.stderr.encode()) == FFMPEG_PROGRESS_STDERR_BYTES
    assert 50 in values and values[-1] == 100


def test_progress_diagnostics_hard_cap_rejects_overflow_and_reaps(monkeypatch):
    import kinocut.ffmpeg_progress as progress
    from kinocut.errors import MCPVideoError

    processes = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(progress, "MAX_SUBPROCESS_STDERR_BYTES", 1024)
    with pytest.raises(MCPVideoError) as error:
        run_progress([sys.executable, "-c", "import os;os.write(2,b'x'*2000000)"], 1, lambda _: None, float)
    assert error.value.code == "command_stderr_limit_exceeded"
    assert processes[0].returncode is not None
    assert processes[0].stderr.closed
