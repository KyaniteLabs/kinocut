"""Every advertised audio container must survive real atomic staging."""

import shutil

import pytest

from kinocut.engine_audio_normalize import normalize_audio
from kinocut.ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg/FFprobe required"
)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "suffix,codec,container",
    [("ogg", "vorbis", "ogg"), ("opus", "opus", "ogg"), ("aif", "pcm_s16be", "aiff"), ("aiff", "pcm_s16be", "aiff")],
)
def test_declared_normalization_suffixes_survive_staging(tmp_path, suffix, codec, container, existing):
    source = tmp_path / "source.wav"
    output = tmp_path / f"normalized.{suffix}"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2:sample_rate=48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(source),
        ]
    )
    if existing:
        output.write_bytes(b"previous output")
    result = normalize_audio(str(source), output_path=str(output))
    metadata = _run_ffprobe_json(result.output_path)
    audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
    assert result.audio_codec == audio["codec_name"] == codec
    assert metadata["format"]["format_name"] == container
    assert audio["channels"] == 2
    assert audio["sample_rate"] == "48000"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
    _run_ffmpeg(["-v", "error", "-xerror", "-i", str(output), "-map", "0:a:0", "-vn", "-f", "null", "-"])
