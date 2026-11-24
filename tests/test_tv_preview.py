"""Verify the artifact and paired-device review contract with real media."""

import hashlib
import json
import os
import subprocess
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut import tv_preview
from kinocut.tv_preview import consume_tv_review_decision, prepare_tv_review_payload, tv_review_messages


def _clip(path, size, sar="1/1"):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={size}:r=6:d=1",
            "-vf",
            f"setsar={sar}",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    return path


def _height(path):
    return int(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=height",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            text=True,
            timeout=30,
        )
    )


def test_downscale_and_build_gadget_messages(tmp_path):
    source = _clip(tmp_path / "tall.mp4", "320x1200")
    prepared = prepare_tv_review_payload(source, caption="Review 03")
    assert prepared["proxy_path"] != str(source)
    assert _height(source) == 1200
    assert _height(prepared["proxy_path"]) == 1080
    assert [stream["codec_type"] for stream in _streams(prepared["proxy_path"])] == ["video"]
    assert _height(prepared["qc_sheet_path"]) == 360
    video_url = "https://reviews.example.test/tall-preview.mp4"
    sheet_url = "https://reviews.example.test/tall-qc.jpg"
    identity = f"review {prepared['review_id']} / SHA-256 {prepared['artifact_sha256'][:12]}"
    title = f"Review 03 — {identity}"
    assert tv_review_messages(prepared, proxy_url=video_url, qc_sheet_url=sheet_url) == [
        {"action": "ui.show_media", "args": {"url": video_url, "kind": "video", "caption": title}},
        {
            "action": "ui.show_media",
            "args": {"url": sheet_url, "kind": "image", "caption": f"{title} — QC contact sheet"},
        },
    ]
    assert prepared["decision_card"] == {
        "title": f"Export this cut? — {identity}",
        "options": ["Approve & export", "Try another range"],
    }


def _streams(path):
    probe = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        timeout=30,
    )
    return json.loads(probe)["streams"]


def test_downscale_preserves_all_audio_tracks_and_tags(tmp_path):
    video = _clip(tmp_path / "video-only.mp4", "320x180")
    source = tmp_path / "multi_audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "2:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-metadata:s:a:0",
            "handler_name=Original",
            "-metadata:s:a:0",
            "language=eng",
            "-metadata:s:a:1",
            "handler_name=Alternate",
            "-metadata:s:a:1",
            "language=spa",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    prepared = prepare_tv_review_payload(source, max_height=90)
    assert _height(prepared["proxy_path"]) == 90
    streams = _streams(prepared["proxy_path"])
    assert [stream["codec_type"] for stream in streams] == ["video", "audio", "audio"]
    assert [(stream["tags"]["handler_name"], stream["tags"]["language"]) for stream in streams[1:]] == [
        ("Original", "eng"),
        ("Alternate", "spa"),
    ]


def test_reuse_small_clip_and_supplied_sheet(tmp_path):
    source = _clip(tmp_path / "small.mp4", "320x180")
    sheet = tmp_path / "qc.jpg"
    sheet.write_bytes(b"provided sheet")
    prepared = prepare_tv_review_payload(source, qc_sheet_path=sheet)
    assert prepared["proxy_path"] == str(source)
    assert prepared["qc_sheet_path"] == str(sheet)
    assert prepared["messages"][0]["args"]["url"] is None
    target = tmp_path / "copy.mp4"
    copied = prepare_tv_review_payload(source, qc_sheet_path=sheet, proxy_output_path=target)
    assert Path(copied["proxy_path"]).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("limit", [True, 1, 1081])
def test_reject_invalid_height(limit):
    with pytest.raises(MCPVideoError, match="2 to 1080"):
        prepare_tv_review_payload("unused.mp4", max_height=limit)


def test_reject_filesystem_urls_and_output_alias(tmp_path):
    source = _clip(tmp_path / "small.mp4", "320x180")
    with pytest.raises(MCPVideoError):
        prepare_tv_review_payload(source, proxy_output_path=source)
    prepared = prepare_tv_review_payload(source)
    with pytest.raises(MCPVideoError, match="TV-reachable"):
        tv_review_messages(prepared, proxy_url=source.as_uri(), qc_sheet_url="https://reviews.example.test/qc.jpg")


@pytest.mark.parametrize(
    ("size", "sar", "expected"),
    [("3840x1080", "1/1", (1920, 540)), ("400x1200", "1/1", (360, 1080)), ("1280x720", "2/1", (1920, 540))],
)
def test_proxy_fits_display_bounds_at_original_dar(tmp_path, size, sar, expected):
    source = _clip(tmp_path / "cut.mp4", size, sar)
    review = prepare_tv_review_payload(source)
    stream = _streams(review["proxy_path"])[0]
    width, height = stream["width"], stream["height"]
    assert (width, height) == expected
    assert stream["sample_aspect_ratio"] == "1:1"
    source_width, source_height = map(int, size.split("x"))
    assert Fraction(width, height) == Fraction(source_width, source_height) * Fraction(sar)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-backed encoder and symlinks")
@pytest.mark.parametrize("writer", ["copy", "transcode", "sheet"])
def test_tv_writer_does_not_follow_swapped_stage(tmp_path, monkeypatch, writer):
    source = _clip(tmp_path / "cut.mp4", "320x1200" if writer == "transcode" else "320x180")
    victim = tmp_path / "victim"
    victim.write_bytes(b"must survive")
    output = tmp_path / "proxy.mp4"
    atomic_output = tv_preview.atomic_output

    @contextmanager
    def swapped_output(path):
        with atomic_output(path) as stage:
            Path(stage).unlink()
            Path(stage).symlink_to(victim)
            yield stage

    monkeypatch.setattr(tv_preview, "atomic_output", swapped_output)
    with pytest.raises(MCPVideoError):
        prepare_tv_review_payload(source, proxy_output_path=output if writer != "sheet" else None)
    assert victim.read_bytes() == b"must survive"
    assert not output.exists()
    assert not list(tmp_path.glob("cut.*.tv-qc.jpg"))


def test_successive_same_path_reviews_reject_stale_and_replayed_approval(tmp_path):
    cut = _clip(tmp_path / "cut.mp4", "320x180")
    first = prepare_tv_review_payload(cut, caption="Review cut")
    cut.unlink()
    _clip(cut, "360x240")
    second = prepare_tv_review_payload(cut, caption="Review cut")
    assert first["artifact_path"] == second["artifact_path"] == str(cut)
    assert first["review_id"] != second["review_id"]
    assert first["artifact_sha256"] != second["artifact_sha256"] == hashlib.sha256(cut.read_bytes()).hexdigest()
    assert first["messages"][0]["args"]["caption"] != second["messages"][0]["args"]["caption"]
    assert first["decision_card"]["title"] != second["decision_card"]["title"]
    with pytest.raises(MCPVideoError) as stale:
        consume_tv_review_decision(first["review_id"], "APPROVE")
    assert stale.value.code == "stale_tv_review"
    assert consume_tv_review_decision(second["review_id"], "APPROVE") == cut
    for invalid_id in ("not-a-review", first["review_id"], second["review_id"]):
        with pytest.raises(MCPVideoError) as rejected:
            consume_tv_review_decision(invalid_id, "APPROVE")
        assert rejected.value.code == "unknown_tv_review"


def test_tv_review_rejects_modified_proxy(tmp_path):
    cut = _clip(tmp_path / "cut.mp4", "320x180")
    proxy = tmp_path / "proxy.mp4"
    review = prepare_tv_review_payload(cut, proxy_output_path=proxy)
    proxy.write_bytes(b"different content")
    with pytest.raises(MCPVideoError) as stale:
        consume_tv_review_decision(review["review_id"], "APPROVE")
    assert stale.value.code == "stale_tv_review"
