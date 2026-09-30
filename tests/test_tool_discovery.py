"""Discovery task regressions and ranking contracts without media or model calls."""

import pytest

from kinocut.tool_discovery import discover_tools


def _tool(name, description="", required=()):
    return {"name": name, "description": description, "required_params": required}


@pytest.mark.parametrize("query", ["", "   ", "unrelated pineapple accounting"])
def test_empty_and_unrelated_queries_do_not_expand_catalog(query):
    result = discover_tools(query, [_tool("video_trim", "Trim a video"), _tool("search_tools", "Find tools")])
    assert result == {"success": True, "query": query, "count": 0, "tools": []}


def test_complete_meaningful_token_coverage_and_stable_ranking():
    catalog = [
        _tool("z_audio", "Inspect audio waveform", ("input_path",)),
        _tool("partial", "Inspect audio metadata"),
        _tool("a_audio", "Waveform inspection of audio\nAdditional detail."),
    ]
    forward = discover_tools("inspect audio waveform", catalog)
    # Lexical matching does not stem 'Inspect' into 'inspection'; only a tool
    # containing all meaningful tokens is a fallback match.
    assert [tool["name"] for tool in forward["tools"]] == ["z_audio"]
    assert forward["tools"][0]["required_params"] == ["input_path"]
    ties = discover_tools("audio waveform", catalog)
    assert ties == discover_tools("audio waveform", list(reversed(catalog)))


def test_exact_name_precedes_mentions_and_preserves_response_contract():
    result = discover_tools("VIDEO_TRIM", [
        _tool("mention", "Call video_trim before this tool"),
        _tool("video_trim", "Trim video\nArgs: source", ("input_path",)),
        _tool("video_trim_batch", "Trim many clips"),
    ])
    assert [tool["name"] for tool in result["tools"]] == ["video_trim", "video_trim_batch", "mention"]
    assert result["tools"][0] == {
        "name": "video_trim", "description": "Trim video", "required_params": ["input_path"],
    }
    assert result["query"] == "VIDEO_TRIM"
    assert result["count"] == 3


def test_prefix_search_returns_all_matches_and_excludes_discovery():
    catalog = [_tool(f"video_tool_{i}") for i in range(30)] + [_tool("search_tools", "video_")]
    result = discover_tools("video_", catalog)
    assert result["count"] == 30
    assert all(tool["name"] != "search_tools" for tool in result["tools"])


def test_phrase_aliases_use_boundaries_and_only_existing_tools():
    catalog = [_tool("video_resize"), _tool("hyperframes_remove_background")]
    assert discover_tools("portraiture", catalog)["count"] == 0
    assert discover_tools("foreground segmentation", catalog)["tools"][0]["name"] == "hyperframes_remove_background"
    assert discover_tools("remove filler words", catalog)["count"] == 0


@pytest.mark.parametrize(("query", "expected"), [
    ("remove filler words", "video_timeline_edit_plan"),
    ("find pauses", "video_audio_waveform"),
    ("foreground segmentation", "hyperframes_remove_background"),
    ("resume render", "video_workflow_render"),
    ("safe to publish", "video_publish_gate"),
    ("change volume", "audio_effects"),
    ("keep face in frame", "video_visual_transform_plan"),
    ("captions", "video_subtitles"),
    ("portrait", "video_resize"),
])
def test_registered_task_discovery_regressions(query, expected):
    from kinocut.server import search_tools

    result = search_tools(query)
    assert result["success"] is True
    assert result["tools"][0]["name"] == expected
    assert result["count"] == len(result["tools"])
