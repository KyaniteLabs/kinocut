"""Tests for content repurposing planning and package generation."""

import json
import os

from mcp_video.engine_repurpose import repurpose, repurpose_plan


def test_repurpose_plan_default_package_manifest(sample_video, tmp_path):
    result = repurpose_plan(sample_video, output_dir=str(tmp_path / "package"))

    assert result["success"] is True
    assert result["source"]["path"] == sample_video
    assert result["manifest_path"].endswith("repurpose_plan.json")
    assert os.path.isfile(result["manifest_path"])

    platform_names = {variant["platform"] for variant in result["variants"]}
    assert {"youtube", "youtube-shorts", "tiktok", "instagram-reel", "instagram-post"} <= platform_names

    aspect_ratios = {variant["aspect_ratio"] for variant in result["variants"]}
    assert {"16:9", "9:16", "1:1"} <= aspect_ratios

    vertical = next(variant for variant in result["variants"] if variant["platform"] == "youtube-shorts")
    assert vertical["hyperframes_blocks"] == ["captions-slam", "yt-lower-third"]
    assert vertical["render"] is False

    with open(result["manifest_path"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["variants"] == result["variants"]


def test_repurpose_plan_filters_platforms(sample_video, tmp_path):
    result = repurpose_plan(sample_video, output_dir=str(tmp_path), platforms=["youtube", "tiktok"])

    assert [variant["platform"] for variant in result["variants"]] == ["youtube", "tiktok"]


def test_repurpose_renders_vertical_and_horizontal_with_review_artifacts(sample_video, tmp_path):
    result = repurpose(
        sample_video,
        output_dir=str(tmp_path / "rendered"),
        platforms=["youtube", "youtube-shorts"],
        include_release_checkpoint=True,
        min_score=0,
    )

    assert result["success"] is True
    assert os.path.isfile(result["manifest_path"])
    assert {variant["aspect_ratio"] for variant in result["variants"]} == {"16:9", "9:16"}
    for variant in result["variants"]:
        assert variant["render"] is True
        assert os.path.isfile(variant["output_path"])
        assert variant["release_checkpoint"]["thumbnail"]
        assert os.path.isfile(variant["release_checkpoint"]["thumbnail"])


def test_render_after_plan_in_the_same_folder(sample_video, tmp_path):
    """The documented recipe: plan into a folder, then render into the same folder."""
    package = str(tmp_path / "package")
    plan = repurpose_plan(sample_video, output_dir=package, platforms=["youtube"])

    rendered = repurpose(
        sample_video,
        output_dir=package,
        platforms=["youtube"],
        include_release_checkpoint=False,
        min_score=0,
    )

    assert rendered["success"] is True
    assert os.path.isfile(plan["manifest_path"])
    assert rendered["manifest_path"].endswith("repurpose_manifest.json")
    assert rendered["manifest_path"] != plan["manifest_path"]


def test_repurpose_plan_can_replace_its_own_manifest_with_overwrite(sample_video, tmp_path):
    import asyncio

    from kinocut.server import mcp

    package = str(tmp_path / "package")
    args = {"input_path": sample_video, "output_dir": package, "platforms": ["youtube"]}
    first = asyncio.run(mcp.call_tool("video_repurpose_plan", args))
    first_payload = first[1] if isinstance(first, tuple) else first.structuredContent
    assert first_payload["success"] is True

    refused = asyncio.run(mcp.call_tool("video_repurpose_plan", args))
    refused_payload = refused[1] if isinstance(refused, tuple) else refused.structuredContent
    assert refused_payload["success"] is False
    assert "overwrite=true" in refused_payload["error"]["message"]
    assert "new output_path" not in refused_payload["error"]["message"]

    second = asyncio.run(mcp.call_tool("video_repurpose_plan", {**args, "overwrite": True}))
    second_payload = second[1] if isinstance(second, tuple) else second.structuredContent

    assert second_payload["success"] is True
    assert second_payload["manifest_path"] == first_payload["manifest_path"]
