"""Deterministic creation intent preservation without provider generation."""

import pytest

from kinocut.creation_engine import read_style_pack, render_shot_prompt
from kinocut.errors import MCPVideoError


def _project(tmp_path, camera="", lens="", style="STYLE_TEST"):
    (tmp_path / "style.md").write_text("## STYLE_TEST (lane: example)\nsoft light\n")
    (tmp_path / "storyboard.md").write_text(
        "|shot|provider|model|camera|lens|aspect|action|refs|style|neg|mode|duration|\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
        f"|S01|generic|example|{camera}|{lens}|9:16|device reveals evidence||{style}||i2v|5|\n"
    )
    return render_shot_prompt(str(tmp_path), "S01")


@pytest.mark.parametrize("camera,lens", [("dolly-left", ""), ("", "35mm"), ("dolly-left", "35mm")])
def test_camera_and_lens_independently_survive(tmp_path, camera, lens):
    result = _project(tmp_path, camera, lens)
    assert result["camera"] == camera and result["lens"] == lens
    if camera:
        assert f"Camera: {camera}" in result["prompt"]
    if lens:
        assert f"Lens: {lens}" in result["prompt"]
    assert "soft light" in result["prompt"]
    assert result["prompt_dialect"] == "generic"
    assert result["model_dialect_compiled"] is False


@pytest.mark.parametrize(
    "heading", ["## STYLE_TEST (unfinished", "## STYLE_TEST ()", "## STYLE_TEST (a) (b)", "## STYLE_TEST ambiguous"]
)
def test_malformed_declared_heading_rejects(tmp_path, heading):
    source = tmp_path / "style.md"
    source.write_text(heading + "\nsoft light")
    with pytest.raises(MCPVideoError, match="Unsupported style heading"):
        read_style_pack(str(source))


def test_duplicate_heading_rejects_and_nonblock_heading_ends_body(tmp_path):
    source = tmp_path / "style.md"
    source.write_text("## STYLE_TEST\nsoft light\n## Instructions\nnot prompt content\n")
    assert read_style_pack(str(source))["blocks"][0]["body"] == "soft light"
    source.write_text("## STYLE_TEST\na\n## STYLE_TEST (duplicate)\nb")
    with pytest.raises(MCPVideoError, match="Duplicate style heading"):
        read_style_pack(str(source))


def test_missing_referenced_block_still_rejects(tmp_path):
    with pytest.raises(MCPVideoError, match="Referenced style blocks not found"):
        _project(tmp_path, style="STYLE_MISSING")


def test_whitespace_only_annotation_rejects(tmp_path):
    source = tmp_path / "style.md"
    source.write_text("## STYLE_TEST ( )\nsoft light")
    with pytest.raises(MCPVideoError, match="Empty style annotation"):
        read_style_pack(str(source))
