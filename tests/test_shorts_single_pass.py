"""Production-path render, receipt and publication contracts for vertical Shorts."""

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from kinocut import atomic_publication, staged_writers
from kinocut.aivideo import subtitle_advisory
from kinocut.engine_resize import crop_framing_filter
from kinocut.errors import MCPVideoError
from kinocut.product import shorts_flow

PATH_MARK = "«redacted:sk-path»"
CAPTION = "«redacted:sk-caption»"
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")


def _ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", *args], capture_output=True, check=True, timeout=30
    ).stdout


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("source") / f"{PATH_MARK}.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=red:s=640x360:r=10:d=1[first];color=lime:s=640x360:r=10:d=1[second];[first][second]concat=n=2:v=1:a=0",
        "-c:v",
        "libx264",
        str(path),
    )
    return str(path)


def _assert_media(output, mode, captioned):
    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", output]))
    (video,) = streams["streams"]
    assert (video["width"], video["height"]) == (1080, 1920)
    if mode == "crop":
        assert video["sample_aspect_ratio"] == "1:1"
    assert float(video["duration"]) == pytest.approx(1.0, abs=0.01)
    frames = _ffmpeg("-i", output, "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1")
    width, height = video["width"], video["height"]
    stride = width * height
    assert len(frames) == 10 * stride
    for index in range(10):
        plane = frames[index * stride : (index + 1) * stride]
        assert plane[(height // 2) * width + 5] == pytest.approx(76 if index < 4 else 150, abs=5)
        assert (plane[5] < 5) == (mode == "pad")
        rows = [row for row in range(height) if max(plane[row * width : (row + 1) * width]) > 210]
        if captioned and index >= 4:
            low, high = (1760, 1919) if mode == "crop" else (980, 1263)
            assert rows and low <= min(rows) <= max(rows) <= high
        else:
            assert not rows


def _assert_private(value):
    diagnostic = json.dumps(value, ensure_ascii=False, default=str)
    assert PATH_MARK not in diagnostic and CAPTION not in diagnostic


def _assert_receipt(result, output, mode, captioned):
    public = copy.deepcopy(result)
    assert public.pop("output_path") == str(output)
    steps = public["receipt"]["steps"]
    middle = ["vertical_template", "captions"] if mode == "crop" else ["captions", "vertical_template"]
    assert [s["stage"] for s in steps] == ["trim", "merge", *middle, "export"]
    for step in steps:
        if step["stage"] in {"vertical_template", "export"}:
            assert step.pop("output_path") == str(output)
        if step["stage"] != "captions":
            assert step["status"] == "completed"
        elif captioned:
            assert step["status"] == "completed"
            for key in ("entries", "requested_entries"):
                (entry,) = step[key]
                assert entry.pop("text") == CAPTION
                assert entry == {"start": pytest.approx(0.4), "end": pytest.approx(1.0)}
            assert step["subtitle_qa"]["profile"] == "vertical"
            assert step["subtitle_qa"]["cue_count"] == 1
        else:
            assert step["status"] == "skipped"
    _assert_private(public)


@pytest.mark.parametrize("mode", ["crop", "pad"])
@pytest.mark.parametrize("captioned", [True, False])
def test_shorts_matrix(source, tmp_path, monkeypatch, mode, captioned):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assemble = shorts_flow._assemble_segments
    stage = staged_writers.staged_ffmpeg_command
    advisory = subtitle_advisory.subtitle_advisory
    encodes = []
    qa_sources = []

    def observe(cmd, *args):
        if cmd[-1].endswith(".mp4") and not any(
            cmd[index + 1] == "copy" for index, token in enumerate(cmd[:-1]) if token in {"-c", "-c:v", "-vcodec"}
        ):
            encodes.append(cmd)
        return stage(cmd, *args)

    def assembled(*args):
        result = assemble(*args)
        encodes.clear()
        return result

    def inspect_advisory(media, captions, *, profile=None, burn_ass=None):
        assert profile == "vertical"
        assert burn_ass is not None
        ass = Path(burn_ass).read_text(encoding="utf-8")
        width, height = (1080, 1920) if mode == "crop" else (640, 360)
        assert f"PlayResX: {width}\nPlayResY: {height}\n" in ass
        assert f"subtitles='{burn_ass}'" in encodes[0][encodes[0].index("-vf") + 1]
        qa_sources.append(Path(burn_ass))
        return advisory(media, captions, profile=profile, burn_ass=burn_ass)

    monkeypatch.setattr(shorts_flow, "_assemble_segments", assembled)
    monkeypatch.setattr(staged_writers, "staged_ffmpeg_command", observe)
    monkeypatch.setattr(subtitle_advisory, "subtitle_advisory", inspect_advisory)
    output = tmp_path / f"{PATH_MARK}.mp4"
    progress = []
    result = shorts_flow.video_shorts(
        source,
        [(0.2, 0.6), (1.2, 1.8, CAPTION if captioned else None)],
        {"fit_mode": mode, "quality": "low", "caption_style": "FontSize=42"},
        str(output),
        on_progress=progress.append,
    )
    assert len(encodes) == (2 if mode == "pad" and captioned else 1)
    assert len(qa_sources) == int(captioned)
    assert all(not path.exists() for path in qa_sources)
    if mode == "crop":
        assert encodes[0][encodes[0].index("-vf") + 1].partition(",subtitles=")[0] == crop_framing_filter(1080, 1920)
    assert progress == sorted(progress) and 0 <= progress[0] < progress[-1] == pytest.approx(100)
    _assert_media(output, mode, captioned)
    _assert_receipt(result, output, mode, captioned)
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("failure", ["encoder", "publication"])
@pytest.mark.parametrize("mode", ["crop", "pad"])
def test_shorts_failure_private_and_clean(source, tmp_path, monkeypatch, failure, mode):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    output = tmp_path / f"{PATH_MARK}.mp4"
    publish = atomic_publication._publish_without_overwrite
    stage = staged_writers.staged_ffmpeg_command
    injected = []

    def race(anchor, temporary, basename, identity):
        if basename == output.name:
            injected.append(True)
            output.write_bytes(b"concurrent owner")
        return publish(anchor, temporary, basename, identity)

    def reject(cmd, *args):
        if "-vf" in cmd and "subtitles=" in cmd[cmd.index("-vf") + 1]:
            injected.append(True)
            cmd = list(cmd)
            cmd[-1:-1] = ["-f", f"bad_{PATH_MARK}_{CAPTION}"]
        return stage(cmd, *args)

    if failure == "publication":
        monkeypatch.setattr(atomic_publication, "_publish_without_overwrite", race)
    else:
        monkeypatch.setattr(staged_writers, "staged_ffmpeg_command", reject)
    with pytest.raises(MCPVideoError) as caught:
        shorts_flow.video_shorts(source, [(0, 0.2, CAPTION)], {"fit_mode": mode}, str(output))
    assert injected
    _assert_private([str(caught.value), caught.value.to_dict(), getattr(caught.value, "full_stderr", "")])
    if failure == "publication":
        assert output.read_bytes() == b"concurrent owner"
        output.unlink()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("fit_mode", ["crop", "pad"])
@pytest.mark.parametrize(
    ("scratch_name", "out_name"), [("operator's scratch", "plain_out"), ("plain_scratch", "creator's shorts")]
)
def test_captioned_shorts_succeeds_with_apostrophe_in_tmpdir_or_output_dir(
    source, tmp_path, monkeypatch, fit_mode, scratch_name, out_name
):
    scratch = tmp_path / scratch_name
    scratch.mkdir()
    out_dir = tmp_path / out_name
    out_dir.mkdir()
    output = out_dir / "short.mp4"
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    result = shorts_flow.video_shorts(
        source,
        [(0, 0.2, "Apostrophe safe")],
        {"fit_mode": fit_mode, "quality": "low"},
        str(output),
    )
    assert result["output_path"] == str(output) and output.is_file()
    assert list(out_dir.iterdir()) == [output]
    assert not list(scratch.iterdir())


def test_synthesis_workdir_skips_broken_tmpdir_when_preferred_dir_is_safe(tmp_path, monkeypatch):
    from kinocut.engine_subtitles import _synthesis_workdir
    from kinocut.subtitles_common import filter_safe_ass_workdir

    out_dir = tmp_path / "plain_out"
    out_dir.mkdir()
    apostrophe_dir = tmp_path / "creator's out"
    apostrophe_dir.mkdir()
    safe_cwd = tmp_path / "safe_cwd"
    safe_cwd.mkdir()

    def _broken_tempdir() -> str:
        raise FileNotFoundError("missing TMPDIR")

    monkeypatch.setattr(tempfile, "gettempdir", _broken_tempdir)
    monkeypatch.chdir(safe_cwd)
    assert _synthesis_workdir(str(out_dir / "burned.mp4")) == str(out_dir)
    assert _synthesis_workdir(str(apostrophe_dir / "burned.mp4")) == str(safe_cwd)
    assert filter_safe_ass_workdir(str(apostrophe_dir), str(out_dir)) == str(out_dir)


def test_subtitles_fails_closed_when_all_staging_dirs_contain_apostrophe(source, tmp_path, monkeypatch):
    from kinocut.engine_subtitles import subtitles

    apostrophe_dir = tmp_path / "creator's workspace"
    apostrophe_dir.mkdir()
    srt = apostrophe_dir / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,200\nFail closed\n", encoding="utf-8")
    output = apostrophe_dir / "burned.mp4"

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(apostrophe_dir))
    monkeypatch.chdir(apostrophe_dir)
    with pytest.raises(MCPVideoError) as caught:
        subtitles(source, str(srt), output_path=str(output))
    assert caught.value.code == "subtitle_prepare_failed"
    assert "creator's workspace" not in str(caught.value)
    assert not output.exists()


def test_staged_burn_source_writes_through_owned_descriptor_not_reopened_path(source, tmp_path, monkeypatch):
    import os

    from kinocut import subtitles_common

    ass = tmp_path / "authored.ass"
    ass.write_text(
        "[Script Info]\nPlayResX: 640\nPlayResY: 360\n[Events]\nDialogue: 0,0:00:00.00,0:00:00.20,Default,,0,0,0,,Owned\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.mp4"
    victim = tmp_path / "victim.ass"
    victim.write_text("DO_NOT_OVERWRITE", encoding="utf-8")
    real_mkstemp = tempfile.mkstemp

    def _replace_after_create(*args, **kwargs):
        fd, staged_path = real_mkstemp(*args, **kwargs)
        # Simulate an attacker swapping the directory entry before the copy runs.
        os.unlink(staged_path)
        os.symlink(victim, staged_path)
        return fd, staged_path

    monkeypatch.setattr(subtitles_common.tempfile, "mkstemp", _replace_after_create)
    with subtitles_common.staged_burn_source(str(ass), source, str(out)):
        pass
    assert victim.read_text(encoding="utf-8") == "DO_NOT_OVERWRITE"


def test_subtitles_aac_retry_preserves_unrelated_retry_failure(sample_video, tmp_path, monkeypatch):
    from kinocut import engine_subtitles
    from kinocut.errors import ProcessingError

    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,200\nRetry\n", encoding="utf-8")
    out = tmp_path / "out.mp4"
    calls: list[list[str]] = []

    def _runner(args):
        calls.append(list(args))
        if len(calls) == 1:
            raise ProcessingError("ffmpeg", 1, "Could not find tag for codec pcm_s16le in stream #1")
        raise ProcessingError("ffmpeg", 1, "No space left on device")

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", _runner)
    with pytest.raises(ProcessingError) as caught:
        engine_subtitles.subtitles(sample_video, str(srt), output_path=str(out))
    assert len(calls) == 2
    assert "No space left on device" in caught.value.full_stderr
