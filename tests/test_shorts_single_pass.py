"""Production-path render, receipt and publication contracts for vertical Shorts."""

import copy
import json
import shutil
import subprocess
import tempfile

import pytest

from kinocut import atomic_publication, staged_writers
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
    encodes = []

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

    monkeypatch.setattr(shorts_flow, "_assemble_segments", assembled)
    monkeypatch.setattr(staged_writers, "staged_ffmpeg_command", observe)
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
    assert progress == sorted(progress) and 0 <= progress[0] < progress[-1] == pytest.approx(100)
    _assert_media(output, mode, captioned)
    _assert_receipt(result, output, mode, captioned)
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("failure", ["encoder", "publication"])
def test_crop_failure_private_and_clean(source, tmp_path, monkeypatch, failure):
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
        shorts_flow.video_shorts(source, [(0, 0.2, CAPTION)], {"fit_mode": "crop"}, str(output))
    assert injected
    _assert_private([str(caught.value), caught.value.to_dict(), getattr(caught.value, "full_stderr", "")])
    if failure == "publication":
        assert output.read_bytes() == b"concurrent owner"
        output.unlink()
    assert not list(tmp_path.iterdir())
