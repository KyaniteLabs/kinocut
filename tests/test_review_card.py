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
        input_path=f"/tmp/{PAYLOAD}.mp4",
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
