"""Client contract tests for refreshed Hyperframes and repurposing APIs."""

from mcp_video import Client


def test_client_inspect_exposes_new_hyperframes_methods():
    client = Client()

    for method in [
        "hyperframes_snapshot",
        "hyperframes_inspect",
        "hyperframes_info",
        "hyperframes_catalog",
        "hyperframes_capture",
        "hyperframes_tts",
        "hyperframes_transcribe",
        "hyperframes_remove_background",
        "hyperframes_doctor",
        "hyperframes_benchmark",
    ]:
        metadata = client.inspect(method)
        assert metadata["name"] == method
        assert metadata["category"] in {"media", "report"}


def test_client_hyperframes_tts_allows_voice_listing_without_text():
    client = Client()

    metadata = client.inspect("hyperframes_tts")

    assert metadata["parameters"]["text_or_file"] == "str | None"


def test_client_inspect_exposes_repurpose_methods():
    client = Client()

    plan = client.inspect("repurpose_plan")
    render = client.inspect("repurpose")

    assert plan["category"] == "report"
    assert render["category"] == "report"
    assert "platforms" in plan["parameters"]
    assert "include_release_checkpoint" in render["parameters"]
