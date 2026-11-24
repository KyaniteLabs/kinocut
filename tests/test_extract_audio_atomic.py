"""Extraction validates staged audio before publishing it."""

import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut import engine_extract_audio
from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json
from kinocut.output_policy import output_operation

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs FFmpeg")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.wav"
    _run_ffmpeg(["-f", "lavfi", "-i", "sine=d=0.4", str(path)])
    return path


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["encode", "unprobeable", "truncated", "decode_stderr"])
def test_extraction_never_publishes_bad_audio(source, tmp_path, monkeypatch, existing, failure):
    output = tmp_path / "output.wav"
    if existing:
        output.write_bytes(b"original")

    def broken_encode(args):
        if "-xerror" in args and args[-1] == "-":
            if failure == "decode_stderr":
                return subprocess.CompletedProcess(args, 0, stderr="[error] «redacted:sk-path»")
            return _run_ffmpeg(args)
        staged = Path(args[-1])
        if failure == "decode_stderr":
            staged.write_bytes(source.read_bytes())
        elif failure == "truncated":
            staged.write_bytes(source.read_bytes()[:-19])
            assert _run_ffprobe_json(str(staged))["streams"][0]["codec_name"] == "pcm_s16le"
        else:
            staged.write_bytes(b"partial")
        if failure == "encode":
            raise ProcessingError("ffmpeg", 1, "«redacted:sk-path»")
        return subprocess.CompletedProcess(args, 0, stderr="")

    monkeypatch.setattr(engine_extract_audio, "_run_ffmpeg", broken_encode)
    with output_operation(existing), pytest.raises(MCPVideoError) as exc:
        engine_extract_audio.extract_audio(str(source), str(output), "wav")
    assert "«redacted:sk-path»" not in str(exc.value.to_dict())
    assert set(tmp_path.iterdir()) == ({source, output} if existing else {source})
    if existing:
        assert output.read_bytes() == b"original"


@pytest.mark.parametrize(
    "format, codec", [("mp3", "mp3"), ("aac", "aac"), ("wav", "pcm_s16le"), ("ogg", "vorbis"), ("flac", "flac")]
)
def test_extraction_returns_published_path_and_decodable_audio(source, tmp_path, format, codec):
    output = str(tmp_path / f"output.{format}")
    assert engine_extract_audio.extract_audio(str(source), output, format) == output
    assert [(stream["codec_type"], stream["codec_name"]) for stream in _run_ffprobe_json(output)["streams"]] == [
        ("audio", codec)
    ]
    assert not _run_ffmpeg(["-v", "error", "-xerror", "-i", output, "-f", "null", "-"]).stderr
