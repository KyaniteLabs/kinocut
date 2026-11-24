"""Verify the artifact and paired-device review contract with real media."""

import subprocess
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.tv_preview import prepare_tv_review_payload, tv_review_messages


def _clip(path, size):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={size}:r=6:d=1",
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
    assert _height(prepared["qc_sheet_path"]) == 360
    video_url = "https://reviews.example.test/tall-preview.mp4"
    sheet_url = "https://reviews.example.test/tall-qc.jpg"
    assert tv_review_messages(prepared, proxy_url=video_url, qc_sheet_url=sheet_url) == [
        {"action": "ui.show_media", "args": {"url": video_url, "kind": "video", "caption": "Review 03"}},
        {
            "action": "ui.show_media",
            "args": {"url": sheet_url, "kind": "image", "caption": "Review 03 — QC contact sheet"},
        },
    ]
    assert prepared["decision_card"] == {
        "title": "Export this cut?",
        "options": ["Approve & export", "Try another range"],
    }


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
