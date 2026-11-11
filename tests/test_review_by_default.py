"""Media-writing tools return a review card unless told not to (#767)."""

from __future__ import annotations

import asyncio
import os

from kinocut import review_card, server_tools_basic
from kinocut.errors import MCPVideoError


def _trim(sample_video, tmp_path, **kwargs):
    out = str(tmp_path / "clip.mp4")
    return asyncio.run(server_tools_basic.video_trim(sample_video, start="0", duration="1", output_path=out, **kwargs))


def test_plain_trim_ends_with_a_card(sample_video, tmp_path):
    result = _trim(sample_video, tmp_path)
    assert result["success"] is True
    card = result["review_card"]
    assert card["created"] is True
    assert os.path.isfile(card["output_path"])
    assert result["preview_directive"] == f'::preview{{file="{card["output_path"]}"}}'


def test_review_false_skips_the_card(sample_video, tmp_path):
    result = _trim(sample_video, tmp_path, review=False)
    assert result["success"] is True
    assert "review_card" not in result and "preview_directive" not in result
    assert not any(name.endswith(".html") for name in os.listdir(tmp_path))


def test_merge_ends_with_a_card(sample_video, tmp_path):
    out = str(tmp_path / "merged.mp4")
    result = asyncio.run(server_tools_basic.video_merge([sample_video, sample_video], output_path=out))
    assert result["success"] is True
    assert result["review_card"]["created"] is True
    assert result["preview_directive"].startswith("::preview{file=")


def test_a_failed_card_does_not_fail_the_edit(sample_video, tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise MCPVideoError("no frames", error_type="processing_error", code="no_frames")

    monkeypatch.setattr(review_card, "write_review_card", broken)
    result = _trim(sample_video, tmp_path)
    assert result["success"] is True
    assert os.path.isfile(result["output_path"])
    assert result["review_card"]["created"] is False
    assert result["review_card"]["error"]["code"] == "no_frames"
    assert "preview_directive" not in result


def test_failed_edit_gets_no_card(tmp_path):
    result = asyncio.run(server_tools_basic.video_trim(str(tmp_path / "missing.mp4"), start="0", duration="1"))
    assert result["success"] is False
    assert "review_card" not in result


def test_shorts_ends_with_a_card(sample_video, tmp_path, monkeypatch):
    import shutil

    from kinocut import server_tools_shorts
    from kinocut.product import shorts_flow

    out = str(tmp_path / "short.mp4")
    shutil.copy(sample_video, out)
    monkeypatch.setattr(shorts_flow, "video_shorts", lambda *a, **k: {"success": True, "output_path": out})
    result = asyncio.run(server_tools_shorts.video_shorts(sample_video, [[0, 1]], output_path=out))
    assert result["review_card"]["created"] is True
    skipped = asyncio.run(server_tools_shorts.video_shorts(sample_video, [[0, 1]], output_path=out, review=False))
    assert "review_card" not in skipped
