"""Wave 1 audit remediation regression tests (P0-01..P0-12 and P1 security/publication fixes)."""

from __future__ import annotations

import gc
import hashlib
import http.server
import json
import stat
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from kinocut.errors import MCPVideoError
from kinocut.models import EditResult
from kinocut.publication import output_operation


def _make_test_video(dest: Path, *, duration: float = 2.0, width: int = 320, height: int = 180) -> str:
    """Create a real tiny MP4 with audio using FFmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size={width}x{height}:rate=10",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(dest)


# ---------------------------------------------------------------------------
# Cluster 1: P0-01 + D1-002 (kinocut/client/base.py)
# ---------------------------------------------------------------------------


def test_p0_01_pipeline_preserves_reused_and_aliased_final_output(tmp_path: Path) -> None:
    """_cleanup_pipeline_intermediates must canonicalize paths and never delete final_output."""
    from kinocut.client.base import ClientBase

    src = tmp_path / "source.mp4"
    src.write_bytes(b"src")
    step1_out = tmp_path / "shared_out.mp4"
    alias_dir = tmp_path / "alias_dir"
    alias_dir.symlink_to(tmp_path)

    class _DemoClient(ClientBase):
        def trim(self, input_path: str, output_path: str | None = None, **kwargs: Any) -> EditResult:
            out = Path(output_path or step1_out)
            out.write_bytes(b"rendered-step1")
            return EditResult(output_path=str(out), operation="trim", duration=1.0)

        def resize(self, input_path: str, output_path: str | None = None, **kwargs: Any) -> EditResult:
            # Return an aliased path pointing to the exact same inode as step1_out
            aliased = str(alias_dir / step1_out.name)
            return EditResult(output_path=aliased, operation="resize", duration=1.0)

    client = _DemoClient()
    result = client.pipeline(
        [
            {"op": "trim", "input_path": str(src), "output_path": str(step1_out)},
            {"op": "resize"},
        ],
        cleanup=True,
    )
    assert step1_out.is_file()
    assert step1_out.read_bytes() == b"rendered-step1"
    assert Path(result.output_path).read_bytes() == b"rendered-step1"


def test_d1_002_pipeline_quality_gate_bound_to_final_artifact(tmp_path: Path) -> None:
    """An earlier quality gate on an intermediate cut must not satisfy a later final render."""
    from kinocut.client.base import ClientBase

    src = tmp_path / "src.mp4"
    src.write_bytes(b"src")
    cut1 = tmp_path / "cut1.mp4"
    cut2 = tmp_path / "cut2.mp4"

    class _GateClient(ClientBase):
        def trim(self, input_path: str, output_path: str | None = None, **kwargs: Any) -> EditResult:
            cut1.write_bytes(b"cut1")
            return EditResult(output_path=str(cut1), operation="trim", duration=1.0)

        def resize(self, input_path: str, output_path: str | None = None, **kwargs: Any) -> EditResult:
            cut2.write_bytes(b"cut2")
            return EditResult(output_path=str(cut2), operation="resize", duration=1.0)

        def assert_quality(self, input_path: str, **kwargs: Any) -> dict[str, Any]:
            return {"passed": True, "score": 95.0, "video_path": input_path}

        def quality_check(self, input_path: str, **kwargs: Any) -> dict[str, Any]:
            return {"passed": True, "score": 95.0, "video_path": input_path}

    client = _GateClient()
    # Gate ran on cut1, then resize produced cut2 -> warning MUST report missing release checkpoint
    res_stale = client.pipeline(
        [
            {"op": "trim", "input_path": str(src)},
            {"op": "assert_quality"},
            {"op": "resize"},
        ],
        cleanup=False,
    )
    assert any("release checkpoint" in w for w in res_stale.warnings)

    # Gate ran on cut1, followed only by read-only quality_check on cut1 -> NO missing-checkpoint warning
    res_valid = client.pipeline(
        [
            {"op": "trim", "input_path": str(src)},
            {"op": "assert_quality"},
            {"op": "quality_check"},
        ],
        cleanup=False,
    )
    assert Path(res_valid.output_path).resolve() == cut1.resolve()
    assert not any("release checkpoint" in w for w in res_valid.warnings)


# ---------------------------------------------------------------------------
# Cluster 2: P0-02 + P0-03 + D2-003 (engine_frames.py, engine_storyboard.py)
# ---------------------------------------------------------------------------


def test_p0_02_export_frames_overwrite_policy_and_symlink_guard(tmp_path: Path) -> None:
    """export_frames must refuse overwriting existing frames by default and reject symlink dirs."""
    from kinocut.engine_frames import export_frames

    video = _make_test_video(tmp_path / "clip.mp4", duration=1.5)
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    existing = out_dir / "frame_0001.jpg"
    existing.write_bytes(b"PRECIOUS_USER_IMAGE")

    with pytest.raises(MCPVideoError) as exc_info:
        export_frames(video, output_dir=str(out_dir), fps=1.0, format="jpg")
    assert exc_info.value.code == "output_exists"
    assert existing.read_bytes() == b"PRECIOUS_USER_IMAGE"

    # Symlink output directory must be rejected
    real_dir = tmp_path / "real_frames"
    real_dir.mkdir()
    link_dir = tmp_path / "link_frames"
    link_dir.symlink_to(real_dir)
    with pytest.raises(MCPVideoError):
        export_frames(video, output_dir=str(link_dir), fps=1.0, format="jpg")

    # With explicit overwrite consent, replacement succeeds
    with output_operation(overwrite=True):
        res = export_frames(video, output_dir=str(out_dir), fps=1.0, format="jpg")
    assert res.frame_count >= 1
    assert existing.read_bytes() != b"PRECIOUS_USER_IMAGE"


def test_p0_03_and_d2_003_storyboard_overwrite_and_ragged_grid(tmp_path: Path) -> None:
    """storyboard refuses overwriting existing grid by default and handles ragged last rows."""
    from kinocut.engine_storyboard import storyboard

    video = _make_test_video(tmp_path / "clip.mp4", duration=3.0)
    out_dir = tmp_path / "sb_existing"
    out_dir.mkdir()
    existing_grid = out_dir / "storyboard_grid.jpg"
    existing_grid.write_bytes(b"PRECIOUS_GRID")

    with pytest.raises(MCPVideoError) as exc_info:
        storyboard(video, frame_count=4, output_dir=str(out_dir))
    assert exc_info.value.code == "output_exists"
    assert existing_grid.read_bytes() == b"PRECIOUS_GRID"

    # D2-003: verify single row, full rows, and ragged last rows (2, 4, 5, 6, 7, 8 frames)
    for count in (2, 4, 5, 6, 7, 8):
        sb_dir = tmp_path / f"sb_{count}"
        res = storyboard(video, frame_count=count, output_dir=str(sb_dir))
        assert res.grid is not None
        grid_file = Path(res.grid)
        assert grid_file.is_file() and grid_file.stat().st_size > 0


# ---------------------------------------------------------------------------
# Cluster 3: P0-04 + C1-017 + C1-019 (sphere_plan, storyboard, render, assembly)
# ---------------------------------------------------------------------------


def test_p0_04_c1_017_c1_019_sphere_security_and_approval_binding(tmp_path: Path) -> None:
    """Sphere camera ids reject traversal, work_dir is validated, and approval binds plan digest."""
    from kinocut.te.sphere_assembly import approve_and_render
    from kinocut.te.sphere_plan import decide_sphere_plan, require_approved, validate_sphere_plan
    from kinocut.te.sphere_render import render_sphere_plan

    video = _make_test_video(tmp_path / "sphere.mp4", duration=1.0, width=640, height=320)
    video_sha = hashlib.sha256(Path(video).read_bytes()).hexdigest()

    def _base_plan(cam_id: str = "front") -> dict[str, Any]:
        return {
            "artifact_kind": "360_assembly_plan",
            "schema_version": 1,
            "source": {
                "path": video,
                "duration_seconds": 1.0,
                "width": 640,
                "height": 320,
                "fps": 10.0,
                "sha256": f"sha256:{video_sha}",
            },
            "projection": "equirect",
            "preset": "front_back",
            "status": "proposed",
            "output": {"width": 320, "height": 180, "aspect": "16:9", "fps": 10.0},
            "cameras": [
                {"id": cam_id, "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 90.0},
                {"id": "back", "yaw": 180.0, "pitch": 0.0, "roll": 0.0, "fov": 90.0},
            ],
            "layout": "split",
            "windows": [{"start": 0.0, "end": 1.0, "cameras": [cam_id]}],
            "writer": {"kind": "heuristic"},
        }

    for bad_id in ("../escape", "a/b", r"a\b", "cam\x00x", "", ".", "..", "-leading"):
        with pytest.raises(MCPVideoError):
            validate_sphere_plan(_base_plan(bad_id))

    valid_plan = _base_plan("front")
    approved = decide_sphere_plan(valid_plan, "approve")
    assert "approval" in approved and approved["approval"]["plan_sha256"].startswith("sha256:")
    require_approved(approved)

    # Tampering with plan after approval invalidates approval digest
    tampered = json.loads(json.dumps(approved))
    tampered["cameras"][0]["yaw"] = 45.0
    with pytest.raises(MCPVideoError):
        require_approved(tampered)
    with pytest.raises(MCPVideoError):
        approve_and_render(tampered, str(tmp_path / "out.mp4"), decision="approve")

    # C1-017: render_sphere_plan rejects non-directory or symlink work_dir
    not_a_dir = tmp_path / "file_as_workdir"
    not_a_dir.write_text("not a dir", encoding="utf-8")
    with pytest.raises(MCPVideoError):
        render_sphere_plan(approved, str(tmp_path / "out.mp4"), work_dir=str(not_a_dir))


# ---------------------------------------------------------------------------
# Cluster 4: P0-05 + P0-06 + P0-07 + P0-08 + C1-* + C2-007
# ---------------------------------------------------------------------------


def test_p0_05_and_p0_08_workflow_resume_and_cutfile_second_run(tmp_path: Path) -> None:
    """Workflow in-place resume and 2nd-run cutfile render succeed under default overwrite=False."""
    from kinocut.te.cutfile_render import render_cutfile
    from kinocut.workflow.executor import render_workflow

    _make_test_video(tmp_path / "src.mp4", duration=2.0)
    receipt = tmp_path / "wf_receipt.json"
    spec = {
        "schema_version": 1,
        "name": "resume-test",
        "sources": {"hero": {"path": "src.mp4"}},
        "steps": [
            {
                "id": "s1",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0.0, "end": 1.0},
                "output": "@outputs.final",
            },
        ],
        "outputs": {"final": {"path": "wf_out.mp4"}},
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    # Run 1 + in-place resume under default overwrite=False
    r1 = render_workflow(str(spec_path), save_receipt=str(receipt), keep_intermediates=True)
    assert (tmp_path / r1["outputs"][0]["path"]).is_file()
    r2 = render_workflow(
        str(spec_path),
        resume_receipt=str(receipt),
        save_receipt=str(receipt),
        keep_intermediates=True,
    )
    assert (tmp_path / r2["outputs"][0]["path"]).is_file()

    # Cutfile render run 1 + run 2 under default overwrite=False
    cf_out = tmp_path / "cf_out.mp4"
    cf_receipt = tmp_path / "cf_receipt.json"
    cutfile_file = tmp_path / "demo.cutfile.json"
    cutfile_file.write_text(
        json.dumps(
            {
                "name": "demo",
                "version": 1,
                "sources": [{"id": "hero", "path": "src.mp4"}],
                "ops": [{"op": "trim", "start": 0.0, "end": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    c1 = render_cutfile(str(cutfile_file), output_path=str(cf_out), save_receipt=str(cf_receipt))
    assert Path(c1["output_path"]).is_file()
    c2 = render_cutfile(str(cutfile_file), output_path=str(cf_out), save_receipt=str(cf_receipt))
    assert Path(c2["output_path"]).is_file()

    # Foreign pre-existing receipt (no ownership witness) MUST be refused under default overwrite=False
    foreign_receipt = tmp_path / "foreign.json"
    foreign_receipt.write_text('{"foreign": true}\n', encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc_info:
        render_workflow(str(spec_path), save_receipt=str(foreign_receipt))
    assert exc_info.value.code in {"output_exists", "unsafe_path"}
    assert '"foreign": true' in foreign_receipt.read_text(encoding="utf-8")


def test_p0_06_c1_009_c1_012_shorts_lifecycle_and_package_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full shorts lifecycle works under default overwrite=False; no 'Likely cause: str'; package respects policy."""
    from kinocut.product import shorts_package as shorts_pkg_mod
    from kinocut.product.models import CandidateMoment, TranscriptSegment, canonical_dedup_key
    from kinocut.product.package import package_approved_clip
    from kinocut.product.package_models import PackageLineage
    from kinocut.product.shorts_package import package_approved_candidate
    from kinocut.product.shorts_plan import IntakeReport, ShortsPlan, save_shorts_plan
    from kinocut.product.shorts_render import render_approved_candidate
    from kinocut.product.shorts_review import review_shorts_plan

    video = _make_test_video(tmp_path / "long.mp4", duration=4.0)
    src_sha = hashlib.sha256(Path(video).read_bytes()).hexdigest()
    out_dir = tmp_path / "shorts_out"
    excerpt = "Opening hook line"
    plan = ShortsPlan(
        job_id="shorts_0123456789abcdef",
        project_dir=str(tmp_path),
        output_dir=str(out_dir),
        config={},
        intake=IntakeReport(
            source_path=video,
            source_sha256=src_sha,
            duration=4.0,
            width=320,
            height=180,
            audio_available=True,
            format="mp4",
        ),
        platforms=("youtube-shorts",),
        transcript=(TranscriptSegment(segment_id="seg-1", start=0.0, end=2.5, text=excerpt),),
        proposals=(
            CandidateMoment(
                candidate_id="cand-1",
                start=0.0,
                end=2.5,
                transcript_excerpt=excerpt,
                suggested_title="Opening Hook",
                suggested_hook=excerpt,
                confidence=0.92,
                rationale="strong hook",
                dedup_key=canonical_dedup_key(
                    start=0.0,
                    end=2.5,
                    excerpt=excerpt,
                    sensitivity="none",
                ),
            ),
        ),
    )

    # Save -> review -> render -> package ALL under default overwrite=False (no output_operation(overwrite=True)!)
    save_shorts_plan(plan)
    reviewed = review_shorts_plan(str(out_dir), candidate_id="cand-1", decision="approve")
    assert reviewed.status == "reviewed"
    rendered = render_approved_candidate(str(out_dir), candidate_id="cand-1")
    assert rendered["status"] == "rendered"
    render_video = rendered["renders"][0]["output_path"]
    assert Path(render_video).is_file()

    # Stub QC gate so tiny synthetic testsrc passes packaging cleanly
    monkeypatch.setattr(shorts_pkg_mod, "_gate_package_media", lambda _p: {"passed": True, "score": 95.0})
    packaged = package_approved_candidate(str(out_dir), candidate_id="cand-1")
    assert packaged["status"] == "packaged"
    assert Path(packaged["packages"][0]["manifest_path"]).is_file()

    # C1-009: invalid candidate error must never produce "Likely cause: str"
    with pytest.raises(MCPVideoError) as exc_info:
        review_shorts_plan(str(out_dir), candidate_id="nonexistent-candidate", decision="approve")
    assert "Likely cause: str" not in str(exc_info.value)

    # C1-012: standalone package_approved_clip refuses overwriting unrelated existing file by default
    from kinocut.product.captions import CaptionArtifact
    from kinocut.product.package_models import ThumbnailSpec

    existing_out = tmp_path / "existing_pkg"
    existing_out.mkdir()
    meta_target = existing_out / "metadata.json"
    meta_target.write_text('{"keep": true}\n', encoding="utf-8")
    thumb_path = rendered["renders"][0]["thumbnail_path"]
    with pytest.raises(MCPVideoError) as pkg_exc:
        package_approved_clip(
            package_dir=str(existing_out),
            vertical_video_path=render_video,
            caption_artifact=CaptionArtifact(
                cues=(),
                srt_body="1\n00:00:00,000 --> 00:00:01,000\nHi\n",
                warnings=(),
                low_confidence_token_count=0,
                omitted_token_count=0,
            ),
            candidate=plan.proposals[0],
            thumbnail=ThumbnailSpec(image_path=thumb_path, timestamp=0.5),
            lineage=PackageLineage(candidate_id="cand-1", review_decision_ref="shorts_0123456789abcdef"),
        )
    assert pkg_exc.value.code == "package_write_conflict"
    assert '"keep": true' in meta_target.read_text(encoding="utf-8")


def test_p0_07_c2_013_c2_010_c2pa_export_staging_offline_and_env_scrub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2PA export preflights offline/tool, never leaks unsigned MP4 on failure, scrubs env, and works with overwrite=False."""
    from kinocut.engine_export import export_video

    video = _make_test_video(tmp_path / "src.mp4", duration=1.0)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"claim_generator": "kinocut-test"}), encoding="utf-8")

    # 1) Offline mode blocks before rendering and leaves NO unsigned MP4
    out_offline = tmp_path / "offline_out.mp4"
    monkeypatch.setenv("KINOCUT_OFFLINE", "1")
    with pytest.raises(MCPVideoError) as exc_off:
        export_video(video, output_path=str(out_offline), c2pa_manifest_path=str(manifest))
    assert exc_off.value.code in {"offline_mode", "offline_network_blocked"}
    assert not out_offline.exists()
    monkeypatch.delenv("KINOCUT_OFFLINE", raising=False)

    # 2) Missing c2patool fails BEFORE rendering and leaves NO unsigned MP4
    out_missing = tmp_path / "missing_tool.mp4"
    monkeypatch.setenv("KINOCUT_C2PATOOL", str(tmp_path / "does_not_exist_c2patool"))
    with pytest.raises(MCPVideoError):
        export_video(video, output_path=str(out_missing), c2pa_manifest_path=str(manifest))
    assert not out_missing.exists()

    # 3) Failing c2patool leaves NO unsigned MP4 on disk
    fail_tool = tmp_path / "fail_c2patool"
    fail_tool.write_text("#!/bin/sh\necho 'sign failed' >&2\nexit 1\n", encoding="utf-8")
    fail_tool.chmod(fail_tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("KINOCUT_C2PATOOL", str(fail_tool))
    out_fail = tmp_path / "fail_sign.mp4"
    with pytest.raises(MCPVideoError):
        export_video(video, output_path=str(out_fail), c2pa_manifest_path=str(manifest))
    assert not out_fail.exists()

    # 4) Succeeding c2patool under default overwrite=False works AND does NOT see ambient API keys
    env_dump = tmp_path / "c2pa_env.txt"
    ok_tool = tmp_path / "ok_c2patool"
    ok_tool.write_text(
        f"""#!/usr/bin/env python3
import os, shutil, sys
with open({str(env_dump)!r}, "w") as fh:
    fh.write("\\n".join(sorted(os.environ.keys())))
args = sys.argv[1:]
if "--version" in args:
    print("c2patool 0.9.0")
    sys.exit(0)
if "--output" in args:
    out_idx = args.index("--output") + 1
    shutil.copyfile(args[0], args[out_idx])
    print('{{"active_manifest": "urn:test", "validation_state": "Valid", "validation_status": []}}')
    sys.exit(0)
print('{{"active_manifest": "urn:test", "validation_state": "Valid", "validation_status": []}}')
""",
        encoding="utf-8",
    )
    ok_tool.chmod(ok_tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("KINOCUT_C2PATOOL", str(ok_tool))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-leak")
    out_ok = tmp_path / "signed_out.mp4"
    res = export_video(video, output_path=str(out_ok), c2pa_manifest_path=str(manifest))
    assert Path(res.output_path).is_file()
    assert res.c2pa is not None
    seen_env = set(env_dump.read_text(encoding="utf-8").splitlines())
    assert "ANTHROPIC_API_KEY" not in seen_env
    assert "OPENAI_API_KEY" not in seen_env


def test_c1_010_011_015_019_020_025_c2_007_publication_and_workflow_fixes(tmp_path: Path) -> None:
    """Verify brand_kit, edit_session, init_project, render_dag, variants, receipt scrub, and subtitle precheck."""
    from kinocut.engine_subtitle_generate import generate_subtitles
    from kinocut.render_dag.compiler import CompiledSpec
    from kinocut.te.brand_kit import BrandKit, save_brand_kit
    from kinocut.te.edit_session import _SESSION_LOCKS, session_close, session_open
    from kinocut.te.init_project import init_project
    from kinocut.workflow.receipt import _sanitize_message
    from kinocut.workflow.variants import validate_variant_id

    # C1-010: save_brand_kit updates its own file under default overwrite=False
    bk_path = tmp_path / "brand.json"
    save_brand_kit(str(bk_path), BrandKit(name="v1"))
    save_brand_kit(str(bk_path), BrandKit(name="v2"))
    assert json.loads(bk_path.read_text(encoding="utf-8"))["name"] == "v2"

    # C1-011 + C1-025: edit_session close persists closed session + receipt, and _SESSION_LOCKS stays bounded
    sess_dir = tmp_path / "sess"
    opened = session_open(str(sess_dir), goal="tighten hook")
    closed = session_close(opened["path"], write_receipt=True)
    assert closed["closed_at"] is not None
    assert closed["receipt_path"] is not None and Path(closed["receipt_path"]).is_file()
    gc.collect()
    assert str(Path(opened["path"]).resolve()) not in _SESSION_LOCKS

    # C1-015: init_project rejects dangling symlinks
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / "README.md").symlink_to(tmp_path / "nonexistent_target.md")
    with pytest.raises(MCPVideoError) as exc_init:
        init_project(str(proj_dir))
    assert exc_init.value.code == "unsafe_path"

    # C1-015: CompiledSpec.write refuses overwriting unrelated existing file under default overwrite=False
    existing_spec = tmp_path / "unrelated.json"
    existing_spec.write_text('{"user": true}\n', encoding="utf-8")
    compiled = CompiledSpec(
        spec={"schema_version": 1},
        spec_bytes=b'{"schema_version":1}',
        spec_hash="sha256:0",
        dag_identity="dag:0",
        order=(),
    )
    with pytest.raises(MCPVideoError) as exc_dag:
        compiled.write(str(existing_spec))
    assert exc_dag.value.code in {"output_exists", "unsafe_path"}
    assert '"user": true' in existing_spec.read_text(encoding="utf-8")

    # C1-019: variant id validation rejects path separators & traversal
    for bad_vid in ("../escape", "a/b", r"a\b", "x\x00y", ""):
        with pytest.raises(MCPVideoError):
            validate_variant_id(bad_vid)

    # C2-007: workflow receipt scrubs Windows paths (both \ and /) and secrets
    scrubbed = _sanitize_message(
        r"Failed at C:\Users\alice\clip.mp4 and C:/Users/alice/out.mp4 with HF_TOKEN=topsecret123",
        tmp_path,
    )
    assert "alice" not in scrubbed
    assert "topsecret123" not in scrubbed

    # C1-020: generate_subtitles(burn=True) validates subtitled.mp4 BEFORE writing subtitles.srt
    video = _make_test_video(tmp_path / "sub_src.mp4", duration=1.0)
    sub_dir = tmp_path / "subs_out"
    sub_dir.mkdir()
    (sub_dir / "subtitled.mp4").write_bytes(b"KEEP_ME")
    with pytest.raises(MCPVideoError) as exc_sub:
        generate_subtitles(
            [{"start": 0.0, "end": 0.8, "text": "hello"}],
            video,
            output_path=str(sub_dir / "subtitles.srt"),
            burn=True,
        )
    assert exc_sub.value.code == "output_exists"
    assert not (sub_dir / "subtitles.srt").exists()


# ---------------------------------------------------------------------------
# Cluster 5: P0-09 + P0-10 + D4-006 + C2-012 (offline.py, sound_joins/loudness.py)
# ---------------------------------------------------------------------------


def test_p0_09_p0_10_d4_006_c2_012_offline_ffmpeg_and_loudness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline FFmpeg blocks movie/amovie/lavfi/filter_script/smuggled -h/multi-output/tee with 0 HTTP hits."""
    from kinocut.offline import OfflineModelMissing, offline_media_command

    hits: list[str] = []

    class _TrapHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"TRAP")

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TrapHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("KINOCUT_OFFLINE", "1")
        url = f"http://127.0.0.1:{port}/leak.mp4"
        video = _make_test_video(tmp_path / "local.mp4", duration=0.5)
        out_mp4 = str(tmp_path / "out.mp4")

        # 1) -vf movie=http://...
        cmd1 = offline_media_command(["ffmpeg", "-y", "-i", video, "-vf", f"movie={url}[ov];[0:v][ov]overlay", out_mp4])
        p1 = subprocess.run(cmd1, capture_output=True, text=True, timeout=15)
        assert p1.returncode != 0

        # 2) -af amovie=http://...
        cmd2 = offline_media_command(["ffmpeg", "-y", "-i", video, "-af", f"amovie={url}", out_mp4])
        p2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
        assert p2.returncode != 0

        # 3) -f lavfi -i amovie=http://...
        cmd3 = offline_media_command(["ffmpeg", "-y", "-f", "lavfi", "-i", f"amovie={url}", "-t", "0.2", out_mp4])
        p3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=15)
        assert p3.returncode != 0

        # 4) Smuggled info flag: -metadata comment=-h -i http://...
        cmd4 = offline_media_command(["ffmpeg", "-y", "-metadata", "comment=-h", "-i", url, out_mp4])
        p4 = subprocess.run(cmd4, capture_output=True, text=True, timeout=15)
        assert p4.returncode != 0

        # 5) -filter_complex_script containing movie=http://...
        script_file = tmp_path / "bad_filter.txt"
        script_file.write_text(f"movie={url}[ov];[0:v][ov]overlay", encoding="utf-8")
        with pytest.raises(MCPVideoError):
            offline_media_command(["ffmpeg", "-y", "-i", video, "-filter_complex_script", str(script_file), out_mp4])

        # 6) -f tee to remote URL blocked upfront by offline_media_command
        with pytest.raises(MCPVideoError):
            offline_media_command(["ffmpeg", "-y", "-i", video, "-f", "tee", f"[f=mp4]{url}"])

        # 7) Multi-output where 2nd output is remote URL
        cmd7 = offline_media_command(["ffmpeg", "-y", "-i", video, out_mp4, url])
        p7 = subprocess.run(cmd7, capture_output=True, text=True, timeout=15)
        assert p7.returncode != 0

        assert hits == [], f"Loopback HTTP trap received unexpected requests in offline mode: {hits}"
    finally:
        server.shutdown()
        server.server_close()

    # D4-006: OfflineModelMissing.__str__ must NOT leak expected_file host path
    secret_path = Path("/Users/alice/private/model.bin")
    exc = OfflineModelMissing(secret_path, feature="whisper", env_hint="Set KINOCUT_WHISPER_MODEL")
    assert exc.expected_file == secret_path
    assert str(secret_path) not in str(exc)

    # C2-012: sound_joins/loudness.py routes commands through offline_media_command
    import kinocut.sound_joins.loudness as loudness_mod

    assert hasattr(loudness_mod, "offline_media_command")


# ---------------------------------------------------------------------------
# Cluster 6: P0-11 + D4-003 + C2-004 + C2-005 + C1-013 + C1-024 (ai_engine)
# ---------------------------------------------------------------------------


def test_p0_11_d4_003_c2_004_c2_005_c1_024_ai_engine_hardening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned opener enforces subclasses/http-only; SSRF IP ranges blocked; no silent fallback; redacted errors."""
    import kinocut.ai_engine as ai_pkg
    import kinocut.ai_engine.download as dl
    import kinocut.ai_engine.silence as silence_mod
    import kinocut.ai_engine.stem as stem_mod

    # P0-11: subclass check + clean opener with only http/https handlers
    assert issubclass(dl._PinnedHTTPHandler, urllib.request.HTTPHandler)
    assert issubclass(dl._PinnedHTTPSHandler, urllib.request.HTTPSHandler)
    opener = dl._build_pinned_opener()
    assert set(opener.handle_open.keys()) == {"http", "https"}

    # C2-004: blocked IP ranges and URL scheme/host checks
    for blocked in (
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",  # noqa: S104
        "127.0.0.1",
        "169.254.169.254",
        "::ffff:127.0.0.1",
        "64:ff9b::127.0.0.1",
    ):
        assert dl._is_blocked_ip(blocked) is True, f"Expected {blocked} to be blocked"
    assert dl._is_safe_url("file:///etc/passwd") is False
    assert dl._is_safe_url("ftp://example.com/video.mp4") is False
    assert dl._url_host("https://user:pass@YouTube.com:443/watch?v=1#frag") == "youtube.com:443"

    # D4-003: ssrf_blocked from yt-dlp must NOT fall back to _download_direct_url
    direct_called = False

    def _fail_ssrf(*args: Any, **kwargs: Any) -> str:
        raise MCPVideoError("blocked", error_type="validation_error", code="ssrf_blocked")

    def _spy_direct(*args: Any, **kwargs: Any) -> str:
        nonlocal direct_called
        direct_called = True
        return str(tmp_path / "nope.mp4")

    monkeypatch.setattr(dl, "_is_safe_url", lambda _u: True)
    monkeypatch.setattr(dl, "_download_with_ytdlp", _fail_ssrf)
    monkeypatch.setattr(dl, "_download_direct_url", _spy_direct)
    with pytest.raises(MCPVideoError) as dl_exc:
        dl._resolve_video_source("https://example.com/clip.mp4")
    assert dl_exc.value.code == "ssrf_blocked"
    assert direct_called is False

    # C2-005: _run_analysis redacts secrets and paths in error messages
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom at /Users/alice/secret.mp4 with HF_TOKEN=mysecretvalue")

    analysis_errors: list[str] = []
    ai_pkg._run_analysis(_boom, "demo", analysis_errors)
    assert len(analysis_errors) == 1
    assert "alice" not in analysis_errors[0]
    assert "mysecretvalue" not in analysis_errors[0]

    # C1-024: silence._processing_failure passes int returncode
    src_text = Path(silence_mod.__file__).read_text(encoding="utf-8")
    assert "_processing_failure(" in src_text
    assert '_processing_failure("remove_silence", reason(' not in src_text

    # stem.py: no stale ==2.0.1 pin
    stem_text = Path(stem_mod.__file__).read_text(encoding="utf-8")
    assert "==2.0.1" not in stem_text


# ---------------------------------------------------------------------------
# Cluster 7: P0-12 + D6-009 + C2-009 + C2-010 (hyperframes, revideo, process_tree)
# ---------------------------------------------------------------------------


def test_p0_12_d6_009_c2_009_c2_010_hyperframes_revideo_and_env_scrub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hyperframes capture SSRF + offline gates, fail-closed validate, revideo offline, and env scrubbing."""
    from kinocut import revideo_engine
    from kinocut.hyperframes import ops as hf_ops
    from kinocut.process_tree import sanitized_subprocess_env
    from kinocut.server_tools_hyperframes import hyperframes_capture

    # P0-12: hyperframes_capture blocks SSRF metadata/loopback URLs
    res_meta = hyperframes_capture("http://169.254.169.254/latest/meta-data/")
    assert res_meta["success"] is False
    assert res_meta["error"]["code"] == "ssrf_blocked"

    res_loop = hyperframes_capture("http://127.0.0.1:8080/admin")
    assert res_loop["success"] is False
    assert res_loop["error"]["code"] == "ssrf_blocked"

    # P0-12: offline mode blocks capture, catalog, add_block, tts, remove_background, revideo install_deps
    monkeypatch.setenv("KINOCUT_OFFLINE", "1")
    res_off = hyperframes_capture("https://example.com/")
    assert res_off["success"] is False
    assert res_off["error"]["code"] == "offline_network_blocked"

    for fn in (
        lambda: hf_ops.capture("https://example.com/"),
        lambda: hf_ops.catalog(),
        lambda: hf_ops.add_block(str(tmp_path), "hero"),
        lambda: hf_ops.tts("hello"),
        lambda: hf_ops.remove_background(str(tmp_path / "img.png")),
        lambda: revideo_engine.install_deps(tmp_path),
    ):
        with pytest.raises(MCPVideoError) as off_exc:
            fn()
        assert off_exc.value.code == "offline_network_blocked"
    monkeypatch.delenv("KINOCUT_OFFLINE", raising=False)

    # D6-009 + C2-009: hyperframes.ops.validate fails CLOSED on lint exception and redacts stderr/exc
    proj = tmp_path / "hf_proj"
    proj.mkdir()
    (proj / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(hf_ops, "_hyperframes_command_prefix", lambda cwd: ["npx", "hyperframes"])
    monkeypatch.setattr(hf_ops.current_runner(), "which", lambda _cmd: "/usr/bin/node")
    monkeypatch.setattr(
        hf_ops,
        "_run_hyperframes",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lint boom at /Users/alice/proj HF_TOKEN=supersecret123")),
    )
    val = hf_ops.validate(str(proj))
    assert val.valid is False
    assert len(val.issues) >= 1
    combined_issues = " ".join(val.issues)
    assert "alice" not in combined_issues
    assert "supersecret123" not in combined_issues

    # C2-010: sanitized_subprocess_env strips API keys/tokens/NODE_OPTIONS while preserving PATH
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-123")
    monkeypatch.setenv("HF_TOKEN", "hf_123")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws_123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_123")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/evil.js")
    clean = sanitized_subprocess_env()
    for stripped in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "HF_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "NODE_OPTIONS",
    ):
        assert stripped not in clean
    assert "PATH" in clean


# ---------------------------------------------------------------------------
# Cluster 8: C2-016 + C2-006 + C2-008 + C2-015 + C1-016
# ---------------------------------------------------------------------------


def test_c2_016_c2_006_c2_008_c2_015_c1_016_redaction_worker_and_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redaction covers env secrets, fragments, Windows / paths; glitch/worker/runner/moment attribution hardened."""
    from kinocut import engine_glitch_shader
    from kinocut.projectstore import open_project, render_jobs, render_runner
    from kinocut.projectstore.edit_projects import append_revision, create_edit_project
    from kinocut.projectstore.render_jobs import get_render_job, submit_render_job
    from kinocut.projectstore.semantic_indexes import find_moments, persist_moment_selection, persist_semantic_index
    from kinocut.request_log import redact_text
    from kinocut.semantic.index import build_semantic_index
    from kinocut.semantic.models import AnalyzerProvenance, SemanticTimeline, SourceMedia, WordSpan
    from kinocut.watching import vision_provider_worker

    # C2-016: env-prefixed secrets, URL fragments, and forward-slash Windows paths
    sample = (
        "HF_TOKEN=shortsecret DB_PASSWORD=hunter2 OPENAI_API_KEY=short "
        "https://ex.test/cb#access_token=abc C:/Users/alice/proj/clip.mp4"
    )
    redacted = redact_text(sample)
    for leaked in ("shortsecret", "hunter2", "=short", "access_token=abc", "alice"):
        assert leaked not in redacted, f"{leaked!r} leaked in {redacted!r}"
    assert "#<redacted-fragment>" in redacted

    # C2-008: glitch shader missing_canvas error omits absolute host directory
    monkeypatch.setattr(engine_glitch_shader, "_crush_sources_available", lambda: True)
    monkeypatch.setattr(engine_glitch_shader, "_crush_canvas_available", lambda: False)
    with pytest.raises(MCPVideoError) as gl_exc:
        engine_glitch_shader._check_shader_dependencies()
    assert str(engine_glitch_shader._CRUSH_JS_DIR) not in str(gl_exc.value)

    # C2-015: vision_provider_worker installs ProxyHandler({})
    captured_handlers: list[Any] = []

    class _DummyOpener:
        def open(self, req: Any, timeout: Any = None) -> Any:
            raise RuntimeError("stop-after-capture")

    def _spy_build_opener(*handlers: Any) -> _DummyOpener:
        captured_handlers.extend(handlers)
        return _DummyOpener()

    monkeypatch.setattr(vision_provider_worker, "require_vision_provider", lambda fixed_origin=True: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(urllib.request, "build_opener", _spy_build_opener)
    with pytest.raises(RuntimeError, match="stop-after-capture"):
        vision_provider_worker.fetch_response(b'{"model":"test"}')
    proxy_handlers = [h for h in captured_handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}

    # C2-006: render_runner.main sanitizes unexpected exception without persisting raw repr(exc) host path
    proj = open_project(tmp_path / "rr_proj")
    edit = create_edit_project(proj, created_by="tool:test")
    rev = append_revision(proj, edit.edit_project_id, operation_ids=())
    rr_src = proj.root / "rr_src.mp4"
    _make_test_video(rr_src, duration=1.0)
    spec_file = proj.root / "rr_spec.json"
    spec_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "x",
                "sources": {"hero": {"path": "rr_src.mp4"}},
                "steps": [
                    {
                        "id": "s1",
                        "op": "trim",
                        "inputs": {"src": "@sources.hero"},
                        "params": {"start": 0.0, "end": 0.5},
                        "output": "@outputs.final",
                    }
                ],
                "outputs": {"final": {"path": "rr_out.mp4"}},
            }
        ),
        encoding="utf-8",
    )
    job = submit_render_job(
        proj, edit_project_id=edit.edit_project_id, revision_id=rev.record_id, spec_path=str(spec_file)
    )
    render_jobs.mark_running(proj, job.job_id, 424242)
    monkeypatch.setattr(render_runner, "_await_running_identity", lambda p, j: None)
    monkeypatch.setattr(
        render_runner,
        "run_job",
        lambda p, j: (_ for _ in ()).throw(RuntimeError("/home/alice/secret/file.mp4 HF_TOKEN=topsecret")),
    )
    render_runner.main(["--project", str(proj.root), "--job-id", job.job_id])
    failed_job = get_render_job(proj, job.job_id)
    assert failed_job.error_message is not None
    assert "alice" not in failed_job.error_message
    assert "topsecret" not in failed_job.error_message

    # C1-016: persist_moment_selection defaults to agent:find_moments, NOT human:review
    source = SourceMedia.create(content_sha256="sha256:" + "a" * 64, duration_seconds=4.0)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.semantic",
        analyzer_version="1",
        model_id="local-fixture",
        model_sha256="sha256:" + "b" * 64,
        determinism_scope="fixture",
    )
    word = WordSpan.create(
        source=source,
        start_seconds=0.5,
        end_seconds=1.2,
        confidence=0.95,
        provenance=provenance,
        text="opening",
    )
    index = build_semantic_index(SemanticTimeline.create(source=source, words=(word,)))
    idx_rec = persist_semantic_index(proj, edit.edit_project_id, rev.record_id, index)
    hits = find_moments(proj, edit.edit_project_id, rev.record_id, idx_rec.index_digest, text="opening")
    sel = persist_moment_selection(
        proj, edit.edit_project_id, rev.record_id, idx_rec.index_digest, hits, (hits[0].span_id,)
    )
    assert sel.created_by == "agent:find_moments"
    assert sel.created_by != "human:review"
