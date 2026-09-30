"""Black occupancy is weighted by decoded presentation intervals, not log spans."""

import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.errors import ProcessingError
from kinocut.watching import metrics, run_review


def _render(path: Path, source: str, *extra: str) -> None:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", source, *extra, "-c:v", "ffv1", str(path),
    ], check=True, timeout=20)


@pytest.fixture
def ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")


@pytest.mark.parametrize("seconds,fps", [(0.52, 25), (0.5, 2), (2, 25)])
def test_all_black_video_counts_terminal_frame(tmp_path, ffmpeg, seconds, fps):
    video = tmp_path / "black.mkv"
    _render(video, f"color=black:s=32x32:r={fps}:d={seconds}")
    assert metrics._blackdetect_ratio(str(video), seconds) == pytest.approx(1.0)


def test_short_all_black_clip_fails_default_review(tmp_path, ffmpeg):
    video = tmp_path / "black.mkv"
    _render(video, "color=black:s=32x32:r=25:d=0.52")
    review = run_review(str(video))
    black = next(finding for finding in review.findings if finding.check_id == "black_frames.ratio")
    assert black.severity == "fail"
    assert black.evidence["black_ratio"] == pytest.approx(1.0)
    assert review.blocked and review.verdict == "fail"


@pytest.mark.parametrize("enabled,expected", [
    ("lt(t,0.3)", 0.3),
    ("gte(t,0.9)", 0.1),
    ("lt(t,0.2)+gte(t,0.3)", 0.9),
])
def test_mixed_black_spans_and_nonblack_tail(tmp_path, ffmpeg, enabled, expected):
    video = tmp_path / "mixed.mkv"
    _render(video, "color=white:s=32x32:r=10:d=1", "-vf", f"drawbox=color=black:t=fill:enable='{enabled}'")
    assert metrics._blackdetect_ratio(str(video), 1) == pytest.approx(expected)


def test_black_frame_shorter_than_log_minimum_is_still_counted(tmp_path, ffmpeg):
    video = tmp_path / "last-frame.mkv"
    _render(video, "color=white:s=32x32:r=25:d=1", "-vf", "drawbox=color=black:t=fill:enable='gte(t,0.96)'")
    assert metrics._blackdetect_ratio(str(video), 1) == pytest.approx(0.04)


def test_vfr_coverage_uses_presentation_gaps_instead_of_frame_count(tmp_path, ffmpeg):
    video = tmp_path / "vfr.mkv"
    _render(video, "color=white:s=32x32:r=10:d=1", "-vf",
            "drawbox=color=black:t=fill:enable='lt(t,0.3)',select='eq(n,0)+eq(n,1)+eq(n,3)+eq(n,9)'",
            "-fps_mode", "vfr")
    assert metrics._blackdetect_ratio(str(video), 1) == pytest.approx(0.3)


def test_longer_audio_does_not_dilute_black_video_coverage(tmp_path, ffmpeg):
    video = tmp_path / "long-audio.mkv"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=black:s=32x32:r=10:d=1", "-f", "lavfi", "-i", "sine=duration=3",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(video),
    ], check=True, timeout=20)
    assert metrics._blackdetect_ratio(str(video), 3) == pytest.approx(1.0)


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Descriptor-backed movie input requires procfs")
def test_filename_filter_metacharacters_do_not_change_measurement(tmp_path, ffmpeg):
    video = tmp_path / "clip,[draft]'cut.mkv"
    _render(video, "color=black:s=32x32:r=25:d=0.52")
    assert metrics._blackdetect_ratio(str(video), 0.52) == pytest.approx(1.0)


def test_truncated_decode_does_not_claim_zero_black_ratio(tmp_path, ffmpeg):
    video = tmp_path / "truncated.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=s=64x64:r=10:d=3", "-c:v", "libx264", "-movflags", "+faststart", str(video),
    ], check=True, timeout=20)
    content = video.read_bytes()
    video.write_bytes(content[:int(len(content) * 0.7)])
    assert metrics._blackdetect_ratio(str(video), 3) is None


def test_probe_failure_is_unavailable_and_leaves_no_managed_metadata(tmp_path, monkeypatch):
    video = tmp_path / "fixture.mkv"
    video.write_bytes(b"fixture")
    monkeypatch.setattr(metrics.tempfile, "tempdir", str(tmp_path))

    def fail(*args, **kwargs):
        raise ProcessingError("ffprobe", 1, "failed blackdetect decode")

    monkeypatch.setattr(metrics, "_run_command", fail)
    assert metrics._blackdetect_ratio(str(video), 1) is None
    assert not list(tmp_path.glob("kinocut_black_*"))


def test_zero_exit_with_decoder_errors_is_unavailable(tmp_path, monkeypatch):
    video = tmp_path / "fixture.mkv"
    video.write_bytes(b"fixture")
    def concealed_error(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text(
            "frame|best_effort_timestamp_time=0|duration_time=1\n", encoding="utf-8",
        )
        kwargs["stderr_sink"].write(b"decoder error")
        return subprocess.CompletedProcess([], 0, "", None)

    monkeypatch.setattr(metrics, "_run_command", concealed_error)
    assert metrics._blackdetect_ratio(str(video), 1) is None


@pytest.mark.parametrize("lines", [
    [],
    ["frame|best_effort_timestamp_time=0\n"],
    ["frame|best_effort_timestamp_time=nan|duration_time=0.04\n"],
    ["frame|best_effort_timestamp_time=0|duration_time=0.04\n"] * 2,
])
def test_missing_or_ambiguous_frame_coverage_is_unavailable(lines):
    assert metrics._black_coverage_from_frames(lines) is None


def test_older_ffprobe_packet_duration_supports_terminal_frame():
    lines = ["frame|best_effort_timestamp_time=0|pkt_duration_time=0.5|tag:lavfi.black_start=0\n"]
    assert metrics._black_coverage_from_frames(lines) == pytest.approx(1.0)
