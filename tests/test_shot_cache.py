import json
import sys
from dataclasses import replace

import pytest

from kinocut.bounded_process import run_bounded
from kinocut.errors import MCPVideoError
from kinocut.shot_cache import ShotSpec, compute_shot_digest, render_shot_plan, splice_shots_lossless


def _clip(path, *, codec="libx264", pix="yuv420p", fps=24, size="32x32", timescale=12288):
    proc = run_bounded(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=s={size}:r={fps}",
            "-frames:v",
            "4",
            "-c:v",
            codec,
            "-threads",
            "1",
            "-pix_fmt",
            pix,
            "-video_track_timescale",
            str(timescale),
            str(path),
        ],
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr


def _frames(path):
    result = run_bounded(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-threads", "1", "pipe:1"],
        text=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_edit_only_invokes_one_renderer(tmp_path):
    counter = tmp_path / "renders"
    producer = """import json, os, sys
with open(sys.argv[1], 'a') as log: log.write(sys.argv[2]+'\\n')
os.execvp('ffmpeg', ['ffmpeg','-v','error','-f','lavfi','-i','color=s=32x32:r=24:c='+json.loads(sys.argv[3])['color'],
          '-frames:v',sys.argv[4],'-c:v','libx264','-threads','1',sys.argv[5]])"""
    shots = [
        ShotSpec(
            name,
            (sys.executable, "-c", producer, str(counter), name, "{params}", "{frame_count}", "{output}"),
            frame_count=4,
            params={"color": color},
        )
        for name, color in zip("abc", ["white", "blue", "red"], strict=True)
    ]
    cache = tmp_path / "cache's shots"
    first = render_shot_plan(shots, tmp_path / "first.mp4", cache, max_workers=2, pin_cpus=True)
    assert first["rebuilt"] == list("abc") and first["reused"] == []
    shots[1] = replace(shots[1], params={"color": "black"})
    output = tmp_path / "second.mp4"
    second = render_shot_plan(shots, output, cache, max_workers=2)
    assert second["rebuilt"] == ["b"] and second["reused"] == ["a", "c"]
    assert sorted(counter.read_text().splitlines()) == list("abbc")
    assert second["total_frames"] == 12 and second["output_path"] == str(output)
    assert _frames(output) == b"".join(
        _frames(cache / second["digests"][name] / "media" / "clip.mp4") for name in "abc"
    )


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"codec": "mpeg4"}, "codec_name"),
        ({"pix": "yuv444p"}, "pix_fmt"),
        ({"fps": 30}, "r_frame_rate"),
        ({"timescale": 24000}, "time_base"),
        ({"size": "64x32"}, "width"),
        ({}, "frame_count"),
    ],
)
def test_mismatch_never_publishes(tmp_path, options, field):
    first, second, output = (tmp_path / name for name in ["first.mp4", "second.mp4", "out.mp4"])
    _clip(first)
    _clip(second, **options)
    with pytest.raises(MCPVideoError, match=field) as error:
        splice_shots_lossless([first, second], output, [4, 4 if options else 3])
    assert error.value.code == "concat_stream_mismatch"
    assert not output.exists()


def test_source_range_and_cache_integrity(tmp_path):
    path = tmp_path / "source.mp4"
    _clip(path)
    shot = ShotSpec("trim", source_path=path, start_frame=1, frame_count=2)
    cache = tmp_path / "cache"
    receipt = render_shot_plan([shot], tmp_path / "trim.mp4", cache)
    digest = receipt["digests"]["trim"]
    assert receipt["total_frames"] == 2
    entry = cache / digest / "media"
    assert json.loads((entry / "metadata.json").read_text())["digest"] == digest
    (entry / "clip.mp4").write_bytes(b"corrupted")
    assert render_shot_plan([shot], tmp_path / "repair.mp4", cache)["rebuilt"] == ["trim"]
    assert compute_shot_digest(replace(shot, warmup_frames=1)) != digest
    downstream = replace(shot, dependencies=("up",))
    assert compute_shot_digest(downstream, {"up": "x"}) != compute_shot_digest(downstream, {"up": "y"})
    path.write_bytes(b"changed input")
    assert compute_shot_digest(shot) != digest
