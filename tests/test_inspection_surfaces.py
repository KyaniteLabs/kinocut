"""Public Wave-2 ingest, preflight, and temporal-inspection surfaces."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import pytest

from kinocut.errors import MCPVideoError


def _run_cli(monkeypatch, capsys, *args: str) -> tuple[int, dict]:
    from kinocut.__main__ import main

    monkeypatch.setattr("sys.argv", ["kino", "--format", "json", *args])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code)
    stream = capsys.readouterr()
    payload = json.loads(stream.out or stream.err)
    return code, payload


def _assert_ingest_transports(client, tool, monkeypatch, capsys, project, source):
    lineage = {"generator_model": "model-v1", "provider_id": "provider-v1"}
    kwargs = {
        "lineage": lineage,
        "usage_rights_status": "pending",
        "usage_rights_evidence_ref": "evidence/rights.json",
    }
    expected = client.ingest(project, source, **kwargs)
    assert tool(project, source, **kwargs) == expected
    code, cli_result = _run_cli(
        monkeypatch,
        capsys,
        "video-ingest",
        project,
        source,
        "--lineage-json",
        json.dumps(lineage),
        "--usage-rights-status",
        "pending",
        "--usage-rights-evidence-ref",
        "evidence/rights.json",
    )
    assert code == 0 and cli_result == expected
    assert expected["ingest_options"] == kwargs


def _assert_preflight_transports(client, tool, monkeypatch, capsys, project, asset_id):
    expected = client.preflight(project, asset_id)
    assert tool(project, asset_id) == expected
    code, cli_result = _run_cli(monkeypatch, capsys, "video-preflight", project, asset_id)
    assert code == 0 and cli_result == expected


def _assert_inspect_transports(client, tool, monkeypatch, capsys, project, asset_id):
    regions = [{"name": "title", "region": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2}}]
    expected = client.inspect_temporal(project, asset_id, declared_regions=regions)
    assert tool(project, asset_id, declared_regions=regions) == expected
    code, cli_result = _run_cli(
        monkeypatch,
        capsys,
        "video-inspect-temporal",
        project,
        asset_id,
        "--regions-json",
        json.dumps(regions),
    )
    assert code == 0 and cli_result == expected


def test_all_transports_delegate_to_one_adapter(monkeypatch, tmp_path, capsys):
    from kinocut.aivideo import surfaces
    from kinocut.client import Client
    from kinocut.server_tools_inspection import (
        video_ingest,
        video_inspect_temporal,
        video_preflight,
    )

    calls: list[tuple[str, str, str | None]] = []

    def fake(operation: str, project_dir: str, *, source_path=None, asset_id=None, **kwargs):
        calls.append((operation, project_dir, source_path or asset_id))
        return {
            "success": True,
            "operation": operation,
            "asset_id": asset_id or "sha256:" + "a" * 64,
            "ingest_options": kwargs,
        }

    monkeypatch.setattr(surfaces, "run_inspection_operation", fake)
    project = str(tmp_path / "project")
    source = str(tmp_path / "clip.mp4")
    asset_id = "sha256:" + "b" * 64

    client = Client()
    _assert_ingest_transports(client, video_ingest, monkeypatch, capsys, project, source)
    _assert_preflight_transports(client, video_preflight, monkeypatch, capsys, project, asset_id)
    _assert_inspect_transports(client, video_inspect_temporal, monkeypatch, capsys, project, asset_id)
    assert [item[0] for item in calls] == [
        "ingest",
        "ingest",
        "ingest",
        "preflight",
        "preflight",
        "preflight",
        "inspect_temporal",
        "inspect_temporal",
        "inspect_temporal",
    ]


def test_missing_project_is_not_created(tmp_path):
    from kinocut.aivideo.surfaces import run_inspection_operation

    missing = tmp_path / "missing"
    with pytest.raises(MCPVideoError) as exc:
        run_inspection_operation("preflight", str(missing), asset_id="sha256:" + "a" * 64)
    assert exc.value.code == "inspection_project_missing"
    assert not missing.exists()


def test_existing_project_refuses_symlinked_store_root(tmp_path):
    from kinocut.aivideo.surfaces import run_inspection_operation

    project = tmp_path / "project"
    external = tmp_path / "external-store"
    project.mkdir()
    external.mkdir()
    (project / ".kinocut").symlink_to(external, target_is_directory=True)
    with pytest.raises(MCPVideoError) as exc:
        run_inspection_operation("preflight", str(project), asset_id="sha256:" + "a" * 64)
    assert exc.value.code == "inspection_project_missing"


def test_unknown_and_superseded_assets_fail_closed(tmp_path, sample_video):
    from kinocut.aivideo.ingest import ingest_project_asset
    from kinocut.aivideo.preflight import run_preflight
    from kinocut.aivideo.surfaces import run_inspection_operation
    from kinocut.projectstore import open_project

    project_dir = tmp_path / "project"
    project = open_project(project_dir)
    original = ingest_project_asset(project, sample_video)
    active = run_preflight(project, original)

    unknown = "sha256:" + "f" * 64
    with pytest.raises(MCPVideoError) as exc:
        run_inspection_operation("preflight", str(project_dir), asset_id=unknown)
    assert exc.value.code == "inspection_asset_not_found"

    # The public boundary accepts only asset_id and resolves the active stored
    # record; callers cannot forge or select the superseded record.
    envelope = run_inspection_operation("preflight", str(project_dir), asset_id=active.asset_id)
    assert envelope["asset"]["record_id"] != original.record_id
    assert envelope["asset"]["record_id"] == active.record_id


def test_preflight_rejects_missing_or_tampered_referenced_artifact(tmp_path, sample_video):
    from kinocut.aivideo.surfaces import run_inspection_operation
    from kinocut.projectstore import layout

    project_dir = tmp_path / "project"
    ingested = run_inspection_operation("ingest", str(project_dir), source_path=sample_video)
    first = run_inspection_operation("preflight", str(project_dir), asset_id=ingested["asset_id"])
    artifact_id = first["asset"]["preflight_artifact_id"]
    artifact = project_dir / layout.artifact_relative_path(artifact_id, "preflight.json")
    original_content = artifact.read_text(encoding="utf-8")
    artifact.unlink()

    with pytest.raises(MCPVideoError) as missing:
        run_inspection_operation("preflight", str(project_dir), asset_id=ingested["asset_id"])
    assert missing.value.code == "inspection_preflight_invalid"
    assert str(tmp_path) not in str(missing.value)

    artifact.parent.mkdir(parents=True, exist_ok=True)
    tampered_payload = json.loads(original_content)
    tampered_payload["technical"]["duration"] /= 2
    artifact.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(MCPVideoError) as tampered:
        run_inspection_operation("preflight", str(project_dir), asset_id=ingested["asset_id"])
    assert tampered.value.code == "inspection_preflight_invalid"
    assert str(tmp_path) not in str(tampered.value)


def test_concurrent_fresh_preflight_converges_on_active_record(tmp_path, sample_video):
    from kinocut.aivideo.surfaces import run_inspection_operation
    from kinocut.client import Client

    project_dir = tmp_path / "project"
    ingested = run_inspection_operation("ingest", str(project_dir), source_path=sample_video)

    def preflight() -> dict:
        return Client().preflight(str(project_dir), ingested["asset_id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: preflight(), range(2)))
    assert all(item["success"] is True for item in results)
    assert len({item["asset"]["record_id"] for item in results}) == 1


def _assert_package_shape(result: dict, asset_id: str) -> None:
    package = result["inspection_package"]
    assert result["success"] is True
    assert result["operation"] == "inspect_temporal"
    assert package["source_asset_id"] == asset_id
    assert package["technical_metadata"] is not None
    assert package["preview"] is not None
    assert package["muted_preview"] is not None
    assert package["motion_strip"] is not None
    assert package["sampled_frames"]
    assert len(package["region_crops"]) == len(package["sampled_frames"])
    assert package["frame_difference_measurements"]
    assert package["findings"] == result["temporal_findings"]
    assert package["unavailable_capabilities"] == [
        "visual.motion_intent",
        "visual.generative_defects",
    ]
    expected_capabilities = ("visual.motion_intent", "visual.generative_defects")
    for analysis, capability_id in zip(result["provider_analyses"], expected_capabilities, strict=True):
        assert analysis == {
            "status": "capability_unavailable",
            "provider_id": None,
            "playable_end": pytest.approx(result["playable_end"]),
            "capability": {
                "capability_id": capability_id,
                "available": False,
                "reason_code": "provider_not_configured",
            },
            "findings": [],
        }


def _preview_stream_types(project_dir, package: dict) -> list[list[str]]:
    types: list[list[str]] = []
    for key in ("preview", "muted_preview"):
        artifact = project_dir / package[key]["location"]
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(artifact),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        types.append([item["codec_type"] for item in json.loads(probe.stdout)["streams"]])
    return types


def test_temporal_surface_returns_full_deterministic_package(tmp_path, sample_video):
    from kinocut.aivideo.surfaces import run_inspection_operation

    project_dir = tmp_path / "project"
    ingested = run_inspection_operation("ingest", str(project_dir), source_path=sample_video)
    regions = [
        {
            "name": "title",
            "region": {"x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2},
        }
    ]
    result = run_inspection_operation(
        "inspect_temporal",
        str(project_dir),
        asset_id=ingested["asset_id"],
        declared_regions=regions,
    )

    package = result["inspection_package"]
    _assert_package_shape(result, ingested["asset_id"])
    assert result["inspection_manifest"]["location"].startswith(".kinocut/artifacts/sha256/")
    preview_types = _preview_stream_types(project_dir, package)
    assert preview_types[0] == ["video", "audio"]
    assert preview_types[1] == ["video"]
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert sample_video not in serialized
    repeated = run_inspection_operation(
        "inspect_temporal",
        str(project_dir),
        asset_id=ingested["asset_id"],
        declared_regions=regions,
    )
    assert repeated["inspection_package"] == result["inspection_package"]
    assert repeated["inspection_manifest"] == result["inspection_manifest"]


def test_audio_longer_surface_parity_uses_playable_video_end(monkeypatch, tmp_path, capsys):
    from kinocut.client import Client
    from kinocut.server_tools_inspection import video_inspect_temporal

    source = tmp_path / "long-audio.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=32x32:r=10:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    project = str(tmp_path / "project")
    client = Client()
    asset = client.ingest(project, str(source))
    via_client = client.inspect_temporal(project, asset["asset_id"])
    via_mcp = video_inspect_temporal(project, asset["asset_id"])
    code, via_cli = _run_cli(
        monkeypatch,
        capsys,
        "video-inspect-temporal",
        project,
        asset["asset_id"],
    )
    assert code == 0
    for result in (via_client, via_mcp, via_cli):
        assert result["playable_end"] == pytest.approx(1.0, abs=0.11)
        assert all(
            analysis["playable_end"] == pytest.approx(result["playable_end"])
            for analysis in result["provider_analyses"]
        )


def test_odd_dimension_source_produces_playable_even_previews(tmp_path):
    from kinocut.aivideo.surfaces import run_inspection_operation

    source = tmp_path / "odd.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=321x241:rate=10:duration=1,format=bgr0",
            "-c:v",
            "ffv1",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    source_probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    source_stream = json.loads(source_probe.stdout)["streams"][0]
    assert (source_stream["width"], source_stream["height"]) == (321, 241)
    project = tmp_path / "project"
    asset = run_inspection_operation("ingest", str(project), source_path=str(source))
    result = run_inspection_operation("inspect_temporal", str(project), asset_id=asset["asset_id"])
    for key in ("preview", "muted_preview"):
        preview = project / result["inspection_package"][key]["location"]
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(preview),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["width"] % 2 == 0
        assert stream["height"] % 2 == 0


def test_ingest_lineage_is_validated_and_preserved(tmp_path, sample_video):
    from kinocut.aivideo.surfaces import run_inspection_operation

    result = run_inspection_operation(
        "ingest",
        str(tmp_path / "project"),
        source_path=sample_video,
        lineage={"generator_model": "model-v1", "provider_id": "provider-v1"},
        usage_rights_status="cleared",
        usage_rights_evidence_ref="evidence/rights.json",
    )
    assert result["asset"]["lineage"]["generator_model"] == "model-v1"
    assert result["asset"]["usage_rights_status"] == "cleared"

    with pytest.raises(MCPVideoError) as exc:
        run_inspection_operation(
            "ingest",
            str(tmp_path / "other"),
            source_path=sample_video,
            lineage={"generator_model": "model-v1", "provider_id": "p", "extra": True},
        )
    assert exc.value.code == "inspection_lineage_invalid"
    assert not (tmp_path / "other").exists()


@pytest.mark.parametrize(
    "regions",
    [
        [{"name": "title,drawtext", "region": {"x": 0, "y": 0, "width": 1, "height": 1}}],
        [{"name": f"region_{index}", "region": {"x": 0, "y": 0, "width": 1, "height": 1}} for index in range(33)],
    ],
)
def test_declared_regions_are_bounded_and_privacy_safe(tmp_path, sample_video, regions):
    from kinocut.aivideo.surfaces import run_inspection_operation

    project = tmp_path / "private-project"
    asset = run_inspection_operation("ingest", str(project), source_path=sample_video)
    with pytest.raises(MCPVideoError) as exc:
        run_inspection_operation(
            "inspect_temporal",
            str(project),
            asset_id=asset["asset_id"],
            declared_regions=regions,
        )
    assert exc.value.code == "inspection_regions_invalid"
    assert str(project) not in str(exc.value)
    assert "drawtext" not in str(exc.value)


def test_public_counts_and_client_contracts():
    from kinocut.cli.parser import build_parser
    from kinocut.client import Client
    from kinocut.server import mcp

    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {"video_ingest", "video_preflight", "video_inspect_temporal"} <= tools
    assert len(tools) == 151

    commands = build_parser()._subparsers._group_actions[0].choices
    assert {"video-ingest", "video-preflight", "video-inspect-temporal"} <= set(commands)
    assert len(commands) == 130
    assert Client().inspect("ingest")["return_type"] == "report"
    assert Client().inspect("preflight")["return_type"] == "report"
    assert Client().inspect("inspect_temporal")["return_type"] == "report"
