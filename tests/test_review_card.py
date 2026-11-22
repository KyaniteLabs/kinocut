"""Tests for the Hermes Desktop review card."""

from __future__ import annotations

import os
import re

from kinocut.review_card import MAX_SEND_TEXT, render_review_card, write_review_card

PAYLOAD = "<script>alert(1)</script>"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _render(send: str = PAYLOAD) -> str:
    return render_review_card(
        title=PAYLOAD,
        facts={PAYLOAD: PAYLOAD},
        images=[(PAYLOAD, PNG, "image/png")],
        actions=[(PAYLOAD, send)],
    )


def test_escapes_user_supplied_text():
    doc = _render()
    assert "<script" not in doc
    assert "http://" not in doc and "https://" not in doc
    assert "&lt;script&gt;" in doc


def test_images_are_data_uris():
    doc = _render()
    sources = re.findall(r'<img src="([^"]*)"', doc)
    assert sources and all(src.startswith("data:image/") for src in sources)


def test_send_text_truncated_and_buttons_carry_attribute():
    doc = _render("x" * 900)
    values = re.findall(r'data-hermes-send="([^"]*)"', doc)
    assert len(values) == 1
    assert len(values[0]) == MAX_SEND_TEXT


def test_write_review_card_on_sample_video(sample_video, tmp_path):
    out = str(tmp_path / "card.html")
    result = write_review_card(sample_video, output_path=out, frame_count=4)
    assert result["success"] is True
    assert result["preview_directive"] == f'::preview{{file="{out}"}}'
    assert os.path.isfile(out)
    with open(out, encoding="utf-8") as fh:
        doc = fh.read()
    assert "data-hermes-send" in doc
    assert 'src="data:image/' in doc
    assert "<script" not in doc


def test_visible_text_names_the_file_not_its_directory(sample_video, tmp_path):
    import html as html_mod
    import shutil

    folder = tmp_path / "private-owner-folder"
    folder.mkdir()
    video = str(folder / "clip.mp4")
    shutil.copy(sample_video, video)
    out = write_review_card(video, frame_count=2)["output_path"]
    with open(out, encoding="utf-8") as fh:
        doc = fh.read()
    visible = re.sub(r'data-hermes-send="[^"]*"', "", doc)
    visible = re.sub(r'src="data:[^"]*"', "", visible)
    assert "clip.mp4" in visible
    assert "private-owner-folder" not in html_mod.unescape(visible)
    assert "private-owner-folder" in doc  # the agent still gets the full path


def test_default_path_never_reuses_an_existing_card(sample_video, tmp_path):
    import shutil

    video = str(tmp_path / "clip.mp4")
    shutil.copy(sample_video, video)
    first = write_review_card(video, frame_count=2)["output_path"]
    second = write_review_card(video, frame_count=2)["output_path"]
    assert first.endswith("clip_review_card.html")
    assert second.endswith("clip_review_card_2.html")
    assert os.path.isfile(first) and os.path.isfile(second)


def test_large_sheet_is_downscaled_to_jpeg(tmp_path):
    from PIL import Image

    from kinocut.review_card import MAX_IMAGE_WIDTH, MAX_INLINE_IMAGE_BYTES, _sheet_bytes

    path = tmp_path / "sheet.png"
    Image.effect_noise((2400, 1200), 100).convert("RGB").save(path)
    assert path.stat().st_size > MAX_INLINE_IMAGE_BYTES
    data, mime = _sheet_bytes(str(path))
    assert mime == "image/jpeg"
    with Image.open(__import__("io").BytesIO(data)) as img:
        assert img.width == MAX_IMAGE_WIDTH


def test_large_sheet_downscales_without_pillow(tmp_path, monkeypatch):
    """Pillow is optional; the card must still build on a plain install (2.0.0 regression)."""
    import sys

    from PIL import Image

    from kinocut.review_card import MAX_IMAGE_WIDTH, MAX_INLINE_IMAGE_BYTES, _sheet_bytes

    path = tmp_path / "sheet.png"
    Image.effect_noise((2400, 1200), 100).convert("RGB").save(path)
    assert path.stat().st_size > MAX_INLINE_IMAGE_BYTES
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "PIL", None)
        m.setitem(sys.modules, "PIL.Image", None)
        data, mime = _sheet_bytes(str(path))

    assert mime == "image/jpeg"
    assert data[:2] == b"\xff\xd8"
    import io

    with Image.open(io.BytesIO(data)) as img:
        assert img.width == MAX_IMAGE_WIDTH


def test_approve_runs_the_gate_then_exports_a_final_file(sample_video, tmp_path):
    """#762: Approve & export must lead to a new file, not re-approve one already on disk."""
    from kinocut.review_card import final_export_path

    out = str(tmp_path / "card.html")
    write_review_card(sample_video, output_path=out, frame_count=2)
    with open(out, encoding="utf-8") as fh:
        doc = fh.read()
    approve = re.search(r'data-hermes-send="(Approve this cut[^"]*)"', doc)
    assert approve, "Approve & export button missing"
    text = approve.group(1)
    final = final_export_path(sample_video)
    assert final.endswith("-final.mp4") and final != sample_video
    assert "video_release_checkpoint" in text
    assert f"video_export it to {final}" in text
    assert not os.path.exists(final)


def test_card_plays_the_cut_inline_within_the_preview_cap(sample_video, tmp_path):
    from kinocut.review_card import MAX_CARD_BYTES

    out = str(tmp_path / "card.html")
    result = write_review_card(sample_video, output_path=out, frame_count=4)
    with open(out, encoding="utf-8") as fh:
        doc = fh.read()
    assert result["plays_inline"] is True
    video = re.search(r"<video ([^>]*)>", doc)
    assert video, "card has no player"
    attrs = video.group(1)
    assert 'src="data:video/mp4;base64,' in attrs
    assert 'poster="data:image/jpeg;base64,' in attrs
    for flag in ("muted", "autoplay", "loop", "playsinline", "controls"):
        assert f" {flag}" in attrs
    assert len(doc.encode("utf-8")) <= MAX_CARD_BYTES


def test_poster_skips_black_frames(tmp_path):
    from PIL import Image, ImageStat

    from kinocut.review_card import MIN_POSTER_LUMA, _poster_bytes

    black, dim, bright = (tmp_path / f"{n}.png" for n in ("black", "dim", "bright"))
    Image.new("RGB", (64, 36), (0, 0, 0)).save(black)
    Image.new("RGB", (64, 36), (8, 8, 8)).save(dim)
    Image.new("RGB", (64, 36), (180, 120, 60)).save(bright)

    poster = _poster_bytes([str(black), str(dim), str(bright)])
    with Image.open(__import__("io").BytesIO(poster)) as img:
        assert ImageStat.Stat(img.convert("L")).mean[0] >= MIN_POSTER_LUMA

    fallback = _poster_bytes([str(black), str(dim)])
    with Image.open(__import__("io").BytesIO(fallback)) as img:
        assert ImageStat.Stat(img.convert("L")).mean[0] > 4


def test_cut_too_long_for_the_budget_falls_back_to_stills(sample_video):
    from kinocut.review_card import _preview_bytes

    assert _preview_bytes(sample_video, duration=3600.0, budget=100_000) is None


def test_poster_builds_without_pillow(sample_video, tmp_path, monkeypatch):
    """The poster frame, like the sheet, must not need Pillow."""
    import sys

    from kinocut.review_card import _poster_bytes
    from kinocut.engine_storyboard import storyboard

    board = storyboard(sample_video, output_dir=str(tmp_path / "frames"), frame_count=3)
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "PIL", None)
        m.setitem(sys.modules, "PIL.Image", None)
        data = _poster_bytes(board.frames)
    assert data is not None and data[:2] == b"\xff\xd8"


def test_card_stacks_for_phone_width():
    """At about 390 px the facts stack and the buttons become full-width tap targets."""
    from mcp_video.review_card import render_review_card

    html = render_review_card(title="cut.mp4", facts={"Duration": "0:42"}, images=[], actions=[("Approve", "ok")])
    phone = html.split("@media (max-width:480px){", 1)[1].split("\n}", 1)[0]
    assert "dl{grid-template-columns:1fr" in phone
    assert ".actions{flex-direction:column}" in phone
    assert "min-height:44px" in phone
    assert "overflow-wrap:anywhere" in html, "long file names wrap instead of widening the card"
