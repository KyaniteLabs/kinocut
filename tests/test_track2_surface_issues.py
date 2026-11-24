"""Regressions for the audit's product, publication, and tool contracts."""

import asyncio
import errno
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from kinocut import atomic_publication, doctor
from kinocut.engine_probe import probe
from kinocut.engine_resize import resize
from kinocut.errors import MCPVideoError
from kinocut.product.package_models import parse_package_manifest
from kinocut.product.shorts_flow import video_shorts
from kinocut.product.shorts_package import package_approved_candidate
from kinocut.product.shorts_plan import load_shorts_plan
from kinocut.product.shorts_review import review_shorts_plan
from kinocut.quality_guardrails import VisualQualityGuardrails
from tests.test_shorts_package import _plan_with_renders
from tests.test_tool_families import _call, _payload


@pytest.mark.usefixtures("overwrite_consent")
def test_package_qc_sees_private_copies_and_failed_replacement_preserves_receipts(tmp_path, monkeypatch):
    plan = _plan_with_renders(tmp_path)
    candidate = {"candidate_id": "candidate_01"}
    review_shorts_plan(plan, **candidate, decision="approve")
    destination = Path(plan, "candidate_01", "packages")
    seen = []

    def gate(path, **_kwargs):
        video = Path(path)
        assert not destination.exists()
        assert video.is_file() and not video.is_relative_to(destination)
        seen.append(video.parent.name)
        return {"video": path}

    monkeypatch.setattr("kinocut.quality_guardrails.assert_quality", gate)
    result = package_approved_candidate(plan, **candidate)
    assert set(seen) == {"youtube-shorts", "instagram-reel"}
    for item in result["packages"]:
        manifest = parse_package_manifest(Path(item["manifest_path"]).read_bytes())
        assert manifest.package_root == item["package_root"]
        assert Path(manifest.thumbnail.image_path).is_file()
        assert item["quality"]["video"] in item["asset_paths"]

    before = {path: path.read_bytes() for path in destination.rglob("*") if path.is_file()}
    previous_plan = load_shorts_plan(plan)

    def fail_last(path, **_kwargs):
        assert {entry: entry.read_bytes() for entry in before} == before
        if Path(path).parent.name == "instagram-reel":
            raise MCPVideoError("Quality gate failed", code="quality_gate_failed")
        return {"video": path}

    monkeypatch.setattr("kinocut.quality_guardrails.assert_quality", fail_last)
    with pytest.raises(MCPVideoError, match="Quality gate failed"):
        package_approved_candidate(plan, **candidate, overwrite=True, allow_fail=True)
    assert {path: path.read_bytes() for path in destination.rglob("*") if path.is_file()} == before
    assert load_shorts_plan(plan) == previous_plan
    assert not list(destination.parent.glob(".kinocut_package_*"))


@pytest.mark.usefixtures("overwrite_consent")
@pytest.mark.skipif(sys.platform != "linux", reason="exercise Linux directory exchange")
def test_package_replaces_the_entire_tree_instead_of_mutating_visible_files(tmp_path, monkeypatch):
    plan = _plan_with_renders(tmp_path)
    candidate = {"candidate_id": "candidate_01"}
    review_shorts_plan(plan, **candidate, decision="approve")
    monkeypatch.setattr("kinocut.quality_guardrails.assert_quality", lambda path, **kwargs: {"video": path})
    first = package_approved_candidate(plan, **candidate)
    root = Path(first["packages"][0]["package_root"]).parent
    original_inode = root.stat().st_ino
    with pytest.raises(MCPVideoError) as conflict:
        package_approved_candidate(plan, **candidate)
    assert conflict.value.code == "package_write_conflict"
    assert root.stat().st_ino == original_inode
    second = package_approved_candidate(plan, **candidate, overwrite=True)
    assert root.stat().st_ino != original_inode
    assert {entry["manifest_path"] for entry in first["packages"]} == {
        entry["manifest_path"] for entry in second["packages"]
    }
    assert not list(root.parent.glob(".kinocut_package_*"))


def test_shorts_crop_fills_vertical_frame_and_burns_captions_after_crop(sample_video, tmp_path):
    output = tmp_path / "filled.mp4"
    result = video_shorts(sample_video, [{"start": 0, "end": 1, "text": "In frame"}], {"fit_mode": "crop"}, str(output))
    info = probe(str(output))
    assert (info.width, info.height) == (1080, 1920)
    assert [step["stage"] for step in result["receipt"]["steps"]][-3:] == ["vertical_template", "captions", "export"]
    assert result["receipt"]["steps"][-3]["fit_mode"] == "crop"


def test_resize_rejects_unknown_fit_mode_before_opening_media():
    with pytest.raises(MCPVideoError, match="fit_mode must be pad or crop"):
        resize("not-needed.mp4", fit_mode="stretch")


@pytest.mark.parametrize(
    "rgb, dark_passed", [({"r": 60, "g": 50, "b": 40}, True), ({"r": 75, "g": 50, "b": 25}, False)]
)
def test_dark_grade_has_bounded_color_cast_tolerance(monkeypatch, rgb, dark_passed):
    monkeypatch.setattr(VisualQualityGuardrails, "_get_rgb_means", lambda _guard, _video: rgb)
    default = VisualQualityGuardrails().check_color_balance("unused")
    dark = VisualQualityGuardrails(profile="dark-grade")
    calibrated = dark.check_color_balance("unused")
    assert default.passed is False and calibrated.passed is dark_passed
    assert default.details["max_allowed_deviation"] == 15
    assert calibrated.details["max_allowed_deviation"] == dark.profile.receipt()["color_balance_max_deviation"] == 30


def test_doctor_rejects_an_installed_but_unimportable_upscale_backend(monkeypatch):
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(doctor, "_package_version", lambda name: "1.4.2")
    probes = []

    def failing_probe(command):
        probes.append(command)
        return None

    monkeypatch.setattr(doctor, "_command_version", failing_probe)
    check = doctor._check_package(
        "basicsr", "basicsr", "ai", False, "Use OpenCV", doctor.importlib.util.find_spec, doctor._package_version
    )
    assert len(probes) == 1 and "RRDBNet" in probes[0][-1]
    assert check["ok"] is False and check["required"] is False
    assert "backend import failed" in check["install_hint"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux renameat2(RENAME_NOREPLACE) fallback")
@pytest.mark.parametrize("failure", sorted({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV}))
def test_publication_falls_back_atomically_without_hardlinks(tmp_path, monkeypatch, failure):
    def unsupported(*_args, **_kwargs):
        raise OSError(failure, "not supported")

    monkeypatch.setattr(os, "link", unsupported)
    output = tmp_path / "output.mp4"
    with atomic_publication.anchored_output(str(output), str) as stage:
        Path(stage).write_bytes(b"all the staged bytes")
    assert output.read_bytes() == b"all the staged bytes"
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.skipif(os.name != "posix", reason="POSIX fail-closed fallback")
def test_publication_fails_closed_without_atomic_primitive_or_symlink_follow(tmp_path, monkeypatch):
    output = tmp_path / "output.mp4"
    target = tmp_path / "other.mp4"
    target.write_bytes(b"untouched")

    def race(*_args, **_kwargs):
        output.symlink_to(target)
        raise OSError(errno.ENOTSUP, "no hardlinks")

    def no_rename(*_args, **_kwargs):
        raise OSError(errno.ENOTSUP, "no exclusive rename")

    monkeypatch.setattr(os, "link", race)
    monkeypatch.setattr(atomic_publication, "_rename_exclusive", no_rename)
    with (
        pytest.raises(MCPVideoError, match="preserve directory identity"),
        atomic_publication.anchored_output(str(output), str) as stage,
    ):
        Path(stage).write_bytes(b"unsafe if followed")
    assert output.is_symlink() and target.read_bytes() == b"untouched"

    # Without symlink, failing both link and exclusive rename must never leave a 0-byte file.
    missing = tmp_path / "missing.mp4"
    monkeypatch.setattr(os, "link", no_rename)
    with (
        pytest.raises(MCPVideoError, match="preserve directory identity"),
        atomic_publication.anchored_output(str(missing), str) as stage,
    ):
        Path(stage).write_bytes(b"staged bytes")
    assert not missing.exists()


def test_crop_normalizes_nonsquare_sar_to_9_16_display_aspect(tmp_path):
    import json
    import subprocess

    anamorphic = tmp_path / "anamorphic.mp4"
    cropped = tmp_path / "cropped.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=720x480:r=25:d=0.5",
            "-vf",
            "setsar=8/9",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(anamorphic),
        ],
        check=True,
    )
    resize(str(anamorphic), aspect_ratio="9:16", fit_mode="crop", output_path=str(cropped))
    meta = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(cropped)]
        )
    )
    vs = meta["streams"][0]
    assert (int(vs["width"]), int(vs["height"])) == (1080, 1920)
    assert vs["display_aspect_ratio"] == "9:16"
    assert vs["sample_aspect_ratio"] == "1:1"


def test_dark_grade_color_balance_failure_gates_assert_quality(monkeypatch):
    from kinocut import quality_guardrails

    fake_report = {
        "video": "clip.mp4",
        "overall_score": 92.0,
        "all_passed": False,
        "profile": {"name": "dark-grade", "visual_checks_gate": True, "color_balance_max_deviation": 30.0},
        "checks": [
            {"name": "brightness", "passed": True, "score": 95.0, "details": {}},
            {"name": "contrast", "passed": True, "score": 95.0, "details": {}},
            {"name": "saturation", "passed": True, "score": 95.0, "details": {}},
            {"name": "color_balance", "passed": False, "score": 50.0, "details": {}},
        ],
        "recommendations": ["Reduce color cast"],
    }
    monkeypatch.setattr(quality_guardrails, "quality_check", lambda *a, **kw: fake_report)
    with pytest.raises(MCPVideoError, match="color_balance"):
        quality_guardrails.assert_quality("clip.mp4", profile="dark-grade", require_audio=False)


def test_compact_family_schema_advertises_additional_properties_true():
    from kinocut.server import configure_tool_surface, mcp
    from kinocut.tool_families import FAMILY_OF_OPERATION

    configure_tool_surface()
    try:
        tools = asyncio.run(mcp.list_tools())
        by_name = {tool.name: tool for tool in tools}
        for family in set(FAMILY_OF_OPERATION.values()):
            assert by_name[family].inputSchema["additionalProperties"] is True, family
    finally:
        configure_tool_surface("all")


@pytest.mark.usefixtures("overwrite_consent")
@pytest.mark.skipif(sys.platform != "linux", reason="Linux directory exchange preservation")
def test_package_overwrite_preserves_concurrently_added_unrelated_file(tmp_path, monkeypatch):
    from kinocut.product import shorts_package

    plan = _plan_with_renders(tmp_path)
    candidate = {"candidate_id": "candidate_01"}
    review_shorts_plan(plan, **candidate, decision="approve")
    monkeypatch.setattr("kinocut.quality_guardrails.assert_quality", lambda path, **kwargs: {"video": path})
    first = package_approved_candidate(plan, **candidate)
    root = Path(first["packages"][0]["package_root"]).parent
    real_exchange = shorts_package._rename_exclusive

    def inject_unrelated(anchor, src, dst, *, exchange=False):
        if exchange:
            (root / "youtube-shorts" / "user_notes.txt").write_text("keep me", encoding="utf-8")
        return real_exchange(anchor, src, dst, exchange=exchange)

    monkeypatch.setattr(shorts_package, "_rename_exclusive", inject_unrelated)
    with pytest.raises(MCPVideoError) as exc_info:
        package_approved_candidate(plan, **candidate, overwrite=True)
    assert exc_info.value.code == "package_write_conflict"
    preserved = list(root.parent.glob(f".{root.name}.preserved_*"))
    assert len(preserved) == 1
    assert (preserved[0] / "youtube-shorts" / "user_notes.txt").read_text(encoding="utf-8") == "keep me"


def test_family_accepts_flat_kwargs_but_not_mixed_or_invalid_params(sample_video):
    from kinocut.server import configure_tool_surface

    configure_tool_surface()
    try:
        family = "video_edit_ops"
        flat = {"operation": "video_audio_waveform", "input_path": sample_video, "bins": 2}
        result = _payload(asyncio.run(_call(family, flat)))
        assert result["success"] and len(result["peaks"]) == 2
        for invalid in ({**flat, "params": {}}, {**flat, "bins": True}, {**flat, "unexpected": "private"}):
            result = _payload(asyncio.run(_call(family, invalid)))
            assert result["error"]["code"] == "invalid_parameter"
            assert "private" not in result["error"]["message"]
    finally:
        configure_tool_surface("all")


def test_default_mcp_accepts_flat_family_kwargs_over_stdio(sample_video):
    async def call():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "kinocut", "--mcp"],
            env={key: value for key, value in os.environ.items() if key != "KINOCUT_TOOLS"},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                "video_edit_ops", {"operation": "video_audio_waveform", "input_path": sample_video, "bins": 2}
            )

    result = asyncio.run(call())
    assert not result.isError and len(result.structuredContent["peaks"]) == 2
