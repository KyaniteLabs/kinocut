import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from subprocess import CompletedProcess

import pytest
from kinocut.shot_cache import cache, concat

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


def test_encoder_and_source_argument_in_key(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_bytes(b"identical")
    shutil.copyfile(first, second)
    shot = ShotSpec("copy", ("cp", "{source}", "{output}"), first)
    monkeypatch.setattr(cache, "_encoder_identity", lambda: "ffmpeg A")
    key = compute_shot_digest(shot)
    assert compute_shot_digest(replace(shot, source_path=second)) != key
    monkeypatch.setattr(cache, "_encoder_identity", lambda: "ffmpeg B")
    assert compute_shot_digest(shot) != key
    assert compute_shot_digest(shot, encoder_id="ffmpeg A") == key


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ({1: "x"}, "keys"),
        (float("nan"), "finite"),
        (float("inf"), "finite"),
        ((1, 2), "Unsupported"),
        ({1}, "Unsupported"),
    ],
)
def test_nested_non_json_params(value, reason):
    shot = ShotSpec("card", ("card", "{output}"), params={"nested": [value]})
    with pytest.raises(ValueError, match=reason):
        compute_shot_digest(shot, encoder_id="test")


def test_concurrent_cold_publication(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    _clip(source)
    shot = ShotSpec("source", source_path=source, frame_count=4)
    barrier = Barrier(2)

    def produce(shot, output, upstream):
        barrier.wait(timeout=15)
        shutil.copyfile(source, output)

    monkeypatch.setattr(cache, "_produce", produce)
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(render_shot_plan, [shot], tmp_path / f"{index}.mp4", tmp_path / "cache") for index in range(2)
        ]
        receipts = [future.result() for future in futures]
    assert sorted(r["rebuilt"] for r in receipts) == [[], ["source"]]
    assert sorted(r["reused"] for r in receipts) == [[], ["source"]]
    assert _frames(tmp_path / "0.mp4") == _frames(tmp_path / "1.mp4") == _frames(source)


@pytest.mark.parametrize("name", ["metadata.json", "clip.mp4"])
def test_symlinked_cache_entry_refused(tmp_path, name):
    source = tmp_path / "source.mp4"
    _clip(source)
    shot = ShotSpec("source", source_path=source, start_frame=1, frame_count=2)
    directory = tmp_path / "cache"
    receipt = render_shot_plan([shot], tmp_path / "first.mp4", directory)
    entry = directory / receipt["digests"]["source"] / "media" / name
    target = tmp_path / "untouched"
    target.write_bytes(b"keep")
    entry.unlink()
    entry.symlink_to(target)
    with pytest.raises(MCPVideoError, match="new cache directory") as error:
        render_shot_plan([shot], tmp_path / "second.mp4", directory)
    assert error.value.code == "shot_cache_unsafe_entry" and entry.is_symlink()
    assert target.read_bytes() == b"keep" and not (tmp_path / "second.mp4").exists()


@pytest.mark.parametrize("char", [chr(i) for i in (*range(32), 127, *range(0x80, 0xA0))])
def test_control_character_rejected_before_any_probe(tmp_path, monkeypatch, char):
    monkeypatch.setattr(concat, "_probe", lambda *_: pytest.fail("probed before validating all paths"))
    with pytest.raises(ValueError, match="control characters"):
        splice_shots_lossless([tmp_path / "valid", tmp_path / f"bad{char}path"], tmp_path / "out.mp4")


@pytest.mark.parametrize("bad_name", ["bad\tname", "bad\u0085name", "bad\u009fname"])
def test_resolved_control_character_is_rejected(tmp_path, monkeypatch, bad_name):
    link = tmp_path / "alias"
    link.symlink_to(tmp_path / bad_name)
    monkeypatch.setattr(concat, "_probe", lambda *_: pytest.fail("probed invalid target"))
    with pytest.raises(ValueError, match="control characters"):
        splice_shots_lossless([link], tmp_path / "out.mp4")


@pytest.mark.parametrize("missing_sar", [None, "N/A", "0:1"])
def test_unspecified_sar_allows_matching_clips_and_rejects_conflict(tmp_path, monkeypatch, missing_sar):
    base = dict(
        codec_type="video",
        codec_name="h264",
        pix_fmt="yuv420p",
        r_frame_rate="24/1",
        avg_frame_rate="24/1",
        time_base="1/12288",
        width=32,
        height=32,
        nb_read_frames="4",
    )

    def make_stream(sar):
        data = dict(base)
        if sar is not None:
            data["sample_aspect_ratio"] = sar
        return data

    def probe_same(argv, **kwargs):
        return CompletedProcess(argv, 0, json.dumps({"streams": [make_stream(missing_sar)]}), "")

    monkeypatch.setattr(concat, "run_bounded", probe_same)
    assert concat.verify_concat_compatibility([tmp_path / "only"]) == 4
    assert concat.verify_concat_compatibility([tmp_path / "first", tmp_path / "second"]) == 8

    def probe_conflict(argv, **kwargs):
        sar = "2:1" if argv[-1].endswith("second") else missing_sar
        return CompletedProcess(argv, 0, json.dumps({"streams": [make_stream(sar)]}), "")

    monkeypatch.setattr(concat, "run_bounded", probe_conflict)
    with pytest.raises(MCPVideoError, match="sample_aspect_ratio"):
        concat.verify_concat_compatibility([tmp_path / "first", tmp_path / "second"])


@pytest.mark.parametrize(
    ("field", "value"), [("avg_frame_rate", "25/1"), ("sample_aspect_ratio", "2:1"), ("sample_aspect_ratio", "2:2")]
)
def test_rational_stream_compatibility(tmp_path, monkeypatch, field, value):
    stream = dict(
        codec_type="video",
        codec_name="h264",
        pix_fmt="yuv420p",
        r_frame_rate="24/1",
        avg_frame_rate="24/1",
        sample_aspect_ratio="1:1",
        time_base="1/12288",
        width=32,
        height=32,
        nb_read_frames="4",
    )

    def probe(argv, **kwargs):
        current = {**stream, field: value} if argv[-1].endswith("second") else stream
        return CompletedProcess(argv, 0, json.dumps({"streams": [current]}), "")

    monkeypatch.setattr(concat, "run_bounded", probe)
    monkeypatch.setattr(concat, "_run_ffmpeg", lambda *_: pytest.fail("ran FFmpeg despite mismatch"))
    paths = [tmp_path / "first", tmp_path / "second"]
    if value == "2:2":
        assert concat.verify_concat_compatibility(paths) == 8
    else:
        with pytest.raises(MCPVideoError, match=field):
            splice_shots_lossless(paths, tmp_path / "out.mp4")


def test_cutfile_external_producer_cli(tmp_path):
    source = tmp_path / "input.mp4"
    _clip(source)
    shot = {
        "shot_id": "external",
        "src": "input",
        "frame_count": 4,
        "command": [sys.executable, "-c", "import shutil, sys; shutil.copyfile(*sys.argv[1:])", "{source}", "{output}"],
    }
    spec = tmp_path / "Cutfile.json"
    spec.write_text(
        json.dumps(
            {
                "name": "cards",
                "sources": [{"id": "input", "path": "input.mp4"}],
                "ops": [{"op": "cached_shots", "shots": [shot]}],
            }
        )
    )
    argv = [sys.executable, "-m", "kinocut", "--format", "json", "cutfile-render", str(spec)]
    denied = run_bounded(argv, timeout=30)
    assert denied.returncode != 0 and "cutfile_untrusted_producer" in denied.stderr
    assert not (tmp_path / "shot-cache").exists()
    for run in ("cold", "warm"):
        receipt = tmp_path / f"{run}.json"
        output = tmp_path / f"{run}.mp4"
        proc = run_bounded(
            [*argv, "--allow-external-producers", "--receipt", str(receipt), "-o", str(output)], timeout=30
        )
        assert proc.returncode == 0, proc.stderr
        shot_plan = json.loads(receipt.read_text())["shot_plan"]
        assert shot_plan["rebuilt"] == (["external"] if run == "cold" else [])
        assert shot_plan["reused"] == ([] if run == "cold" else ["external"])
        assert "shot_plan" in proc.stdout and _frames(output) == _frames(source)
