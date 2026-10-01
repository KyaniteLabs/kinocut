"""Visible fade timing and exact crop geometry using native synthetic media."""

import re
import subprocess

import pytest

from kinocut.engine_crop import crop
from kinocut.engine_fade import fade
from kinocut.engine_probe import probe
from kinocut.engine_runtime_utils import _ffmpeg
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _reset_operation_inputs, _run_ffmpeg, _run_ffprobe_json


@pytest.fixture(autouse=True)
def isolated_operation():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _luma(path, time):
    result = subprocess.run(
        [
            _ffmpeg(),
            "-hide_banner",
            "-ss",
            str(time),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return float(re.findall(r"lavfi.signalstats.YAVG=([\d.]+)", result.stderr)[0])


@pytest.mark.parametrize("video_start,audio_duration", [(0, 1), (0, 3), (1, 3)])
def test_fade_tracks_picture_extent_and_origin(tmp_path, video_start, audio_duration):
    source, output = tmp_path / "source.mp4", tmp_path / "output.mp4"
    _run_ffmpeg(
        [
            "-itsoffset",
            str(video_start),
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=160x90:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:d={audio_duration}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "mpeg4",
            "-fps_mode",
            "passthrough",
            "-c:a",
            "aac",
            str(source),
        ]
    )
    metadata = _run_ffprobe_json(str(source))
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    assert float(video["start_time"]) == pytest.approx(video_start)
    assert float(video["duration"]) == pytest.approx(1)
    fade(str(source), fade_in=0.5 if video_start else 0, fade_out=0 if video_start else 0.5, output_path=str(output))
    sample = video_start + (0.08 if video_start else 0.9)
    assert _luma(source, sample) > 230
    assert _luma(output, sample) < 100
    result = _run_ffprobe_json(str(output))
    rendered = next(stream for stream in result["streams"] if stream["codec_type"] == "video")
    assert int(rendered["nb_frames"]) == int(video["nb_frames"])
    assert float(result["format"]["duration"]) == pytest.approx(audio_duration, abs=0.05)


def test_explicit_odd_crop_is_rejected_without_replacing_delivery(tmp_path, sample_video):
    output = tmp_path / "delivery.mp4"
    output.write_bytes(b"previous delivery")
    with pytest.raises(MCPVideoError) as error:
        crop(sample_video, width=81, height=45, output_path=str(output))
    assert error.value.error_type == "validation_error"
    assert output.read_bytes() == b"previous delivery"


def test_percentage_crop_reports_even_encoded_dimensions(tmp_path, sample_video):
    result = crop(sample_video, crop_percent=33, output_path=str(tmp_path / "crop.mp4"))
    info = probe(result.output_path)
    assert (info.width, info.height) == (210, 158)
