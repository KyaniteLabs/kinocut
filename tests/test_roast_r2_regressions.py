"""Regression tests for Round-2 roast audit fixes (U-01, U-03, U-13, U-21, B-DR2/3/4/8/9, #803)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
import yaml

import kinocut
from kinocut.doctor import _check_workspace
from kinocut.errors import HyperframesRenderError, MCPVideoError, ProcessingError
from kinocut.ffmpeg_progress import _Diagnostics
from kinocut.limits import FFMPEG_PROGRESS_STDERR_BYTES
from kinocut.rescue import verifier
from kinocut.te.init_project import init_project
from kinocut.workflow.executor import render_workflow
from kinocut.workflow.validator import validate_workflow_spec


def test_workflow_validator_rejects_unproduced_declared_output(tmp_path):
    """U-01: declaring @outputs.final with no producing step must fail closed."""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"placeholder")
    spec = {
        "schema_version": 1,
        "name": "unproduced-output",
        "sources": {"clip": {"path": "in.mp4"}},
        "outputs": {"final": {"path": "final.mp4"}},
        "steps": [{"id": "inspect", "op": "probe", "inputs": {"src": "@sources.clip"}}],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(MCPVideoError, match="no producing step"):
        validate_workflow_spec(str(spec_path))


def test_workflow_executor_fails_when_step_writes_no_output(tmp_path, monkeypatch):
    """U-01: a producing step that creates no file must fail instead of stamping COMPLETED."""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"placeholder")
    spec = {
        "schema_version": 1,
        "name": "silent-noop",
        "sources": {"clip": {"path": "in.mp4"}},
        "outputs": {"final": {"path": "final.mp4"}},
        "steps": [
            {
                "id": "cut",
                "op": "trim",
                "inputs": {"src": "@sources.clip"},
                "params": {"start": 0, "duration": 1},
                "output": "@outputs.final",
            }
        ],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr("kinocut.workflow.executor._run_step", lambda *a, **kw: None)

    with pytest.raises(MCPVideoError, match="without creating its declared output"):
        render_workflow(str(spec_path))


def test_rescue_verifier_parses_over_5000_packets_and_fails_closed_when_empty(monkeypatch):
    """U-03: packet parsing must not truncate at 5000 and sync_ok must fail closed on empty AV packets."""
    lines = [f"stream_index=0|pts_time={i * 0.01:.3f}|dts_time={i * 0.01:.3f}|duration_time=0.010" for i in range(6000)]
    parsed = verifier._parse_compact_packets("\n".join(lines))
    assert len(parsed) == 6000

    monkeypatch.setattr(verifier, "_sha", lambda p: "sha256:" + "0" * 64)
    monkeypatch.setattr(
        verifier,
        "_run_ffprobe_json",
        lambda p: {
            "format": {"duration": "10.0", "format_name": "mp4"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "avg_frame_rate": "30/1",
                },
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        },
    )
    monkeypatch.setattr(verifier, "_decode", lambda p: (True, ""))
    monkeypatch.setattr(verifier, "_packets", lambda p: [])

    facts = verifier._verification_facts("s.mp4", "m.mp4", "sh.mp4", None, None)
    assert facts["sync_ok"] is False


def test_init_project_validates_path_and_escapes_yaml_name(tmp_path):
    """U-13: init_project must reject traversal paths and serialize cutfile.yaml safely."""
    with pytest.raises(MCPVideoError):
        init_project(str(tmp_path / ".." / "escape_attempt"))

    target = tmp_path / "proj"
    injected_name = 'bad"\nevil: true'
    result = init_project(str(target), name=injected_name)
    parsed = yaml.safe_load((target / "cutfile.yaml").read_text(encoding="utf-8"))
    assert parsed["name"] == injected_name
    assert "evil" not in parsed
    assert result["cutfile"] == str(target / "cutfile.yaml")


def test_package_getattr_preserves_internal_module_not_found(monkeypatch):
    """U-21: ModuleNotFoundError inside a real submodule must not turn into AttributeError."""

    def fake_import(name: str):
        raise ModuleNotFoundError("No module named 'some_missing_dep'", name="some_missing_dep")

    monkeypatch.setattr(kinocut.importlib, "import_module", fake_import)
    with pytest.raises(ModuleNotFoundError, match="some_missing_dep"):
        kinocut.__getattr__("nonexistent_probe_attr_xyz")


def test_ffmpeg_progress_diagnostics_keeps_stderr_tail():
    """B-DR2: fatal errors printed after >64 KiB of banner/progress must survive in captured stderr."""
    filler = b"frame=1 fps=30 time=00:00:01.00\n" * (FFMPEG_PROGRESS_STDERR_BYTES // 10)
    fatal = b"Conversion failed! Invalid data found when processing input\n"
    payload = filler + fatal

    class FakeStderr:
        def __init__(self, data: bytes):
            self._view = memoryview(data)
            self._pos = 0

        def read1(self, n: int) -> bytes:
            if self._pos >= len(self._view):
                return b""
            chunk = bytes(self._view[self._pos : self._pos + n])
            self._pos += len(chunk)
            return chunk

    tree = SimpleNamespace(process=SimpleNamespace(stderr=FakeStderr(payload)), kill=lambda: None)
    diag = _Diagnostics(tree, 10.0, lambda pct: None, lambda ts: 1.0)
    diag.read()
    captured = diag.captured_stderr()
    assert "Conversion failed!" in captured
    assert len(captured.encode("utf-8")) <= FFMPEG_PROGRESS_STDERR_BYTES + 16


def test_check_filter_available_wraps_timeout_in_processing_error(monkeypatch):
    """B-DR9: subprocess.TimeoutExpired during filter probe must become ProcessingError."""
    import kinocut.engine_runtime_utils as rt

    monkeypatch.setattr(rt, "_AVAILABLE_FILTERS", None)
    monkeypatch.setattr(rt, "_ffmpeg", lambda: "ffmpeg")

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ffmpeg", "-filters"], timeout=10)

    monkeypatch.setattr(rt.subprocess, "run", boom)
    with pytest.raises(ProcessingError, match="timed out"):
        rt._check_filter_available("drawtext")


def test_probe_preserves_timeout_processing_error(tmp_path, monkeypatch):
    """B-DR3: ffprobe timeouts must propagate as ProcessingError, not 'Not a valid video file'."""
    import kinocut.engine_probe as ep

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    monkeypatch.setattr(ep, "_cached_info", lambda *a, **kw: None)

    def timeout_probe(*a, **kw):
        raise ProcessingError("ffprobe", -1, "", reason="FFprobe command timed out after 30s")

    monkeypatch.setattr(ep, "_run_ffprobe_json", timeout_probe)
    with pytest.raises(ProcessingError, match="timed out"):
        ep.probe(str(clip))


def test_doctor_workspace_is_not_required():
    """B-DR4: a read-only cwd must not fail required readiness."""
    assert _check_workspace()["required"] is False


def test_hyperframes_render_error_classifies_environment_failures():
    """#803: Chromium/OOM/timeout errors must not misdirect users to index.html."""
    err_browser = HyperframesRenderError("hyperframes render", 1, "Failed to launch Chromium browser sandbox")
    assert "hyperframes-doctor" in err_browser.suggested_action["description"]
    assert "index.html" not in err_browser.suggested_action["description"]

    err_oom = HyperframesRenderError("hyperframes render", 137, "FATAL ERROR: JavaScript heap out of memory")
    assert "out of memory" in err_oom.suggested_action["description"].lower()
    assert "index.html" not in err_oom.suggested_action["description"]


def test_spatial_pan_matrix_preserves_stereo_at_center_and_pans_cleanly():
    """D-16: center pan must be identity (no mono collapse); hard L/R must isolate channels."""
    from kinocut.ai_engine.spatial import _spatial_pan_matrix

    assert _spatial_pan_matrix(0.0) == (1.0, 0.0, 0.0, 1.0)
    assert _spatial_pan_matrix(-1.0) == (1.0, 1.0, 0.0, 0.0)
    assert _spatial_pan_matrix(1.0) == (0.0, 0.0, 1.0, 1.0)
    assert _spatial_pan_matrix(0.5) == (0.5, 0.0, 0.5, 1.0)


def test_resolve_ffmpeg_timeout_honours_override_and_env(monkeypatch):
    """B-DR1: FFmpeg timeout must support explicit override and KINOCUT_FFMPEG_TIMEOUT."""
    from kinocut.limits import DEFAULT_FFMPEG_TIMEOUT, MAX_VIDEO_DURATION, resolve_ffmpeg_timeout

    monkeypatch.delenv("KINOCUT_FFMPEG_TIMEOUT", raising=False)
    assert resolve_ffmpeg_timeout() == float(DEFAULT_FFMPEG_TIMEOUT)
    assert resolve_ffmpeg_timeout(1800) == 1800.0
    assert resolve_ffmpeg_timeout(999999) == float(MAX_VIDEO_DURATION)

    monkeypatch.setenv("KINOCUT_FFMPEG_TIMEOUT", "1200")
    assert resolve_ffmpeg_timeout() == 1200.0
    monkeypatch.setenv("KINOCUT_FFMPEG_TIMEOUT", "not-a-number")
    assert resolve_ffmpeg_timeout() == float(DEFAULT_FFMPEG_TIMEOUT)


def test_staged_writers_find_output_start_ignores_flag_values_equal_to_minus_i():
    """B-DR12: a metadata value literally equal to '-i' must not fool _find_output_start."""
    from kinocut.staged_writers import _find_output_start

    cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-metadata", "-i", "-c:v", "libx264", "out.mp4"]
    assert _find_output_start(cmd) == 4


def test_merge_normalize_needs_detects_mismatched_audio_codecs():
    """S-01: same sample rate but different audio codecs (aac vs mp3) must trigger normalization."""
    from kinocut.engine_merge import _normalize_needs

    a = SimpleNamespace(
        display_resolution="640x360", codec="h264", fps=30.0, audio_codec="aac", audio_sample_rate=44100
    )
    b = SimpleNamespace(
        display_resolution="640x360", codec="h264", fps=30.0, audio_codec="mp3", audio_sample_rate=44100
    )
    needs, mixed = _normalize_needs([a, b])
    assert needs is True
    assert mixed is False


def test_rescue_verifier_rejects_missing_sidecars_and_truncated_share(monkeypatch, tmp_path):
    """S-04 & S-07: missing explicit sidecars and truncated/silent sharing copies must fail checks."""
    monkeypatch.setattr(verifier, "_sha", lambda p: "sha256:" + "0" * 64)

    def fake_probe(p):
        if p == "share.mp4":
            return {
                "format": {"duration": "1.0", "format_name": "mp4"},
                "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"}],
            }
        return {
            "format": {"duration": "4.0", "format_name": "mp4"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "avg_frame_rate": "30/1",
                },
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        }

    monkeypatch.setattr(verifier, "_run_ffprobe_json", fake_probe)
    monkeypatch.setattr(verifier, "_decode", lambda p: (True, ""))
    monkeypatch.setattr(
        verifier,
        "_packets",
        lambda p: [
            {"stream_index": 0, "pts_time": "3.9", "duration_time": "0.1"},
            {"stream_index": 1, "pts_time": "3.9", "duration_time": "0.1"},
        ],
    )
    facts = verifier._verification_facts(
        "src.mp4",
        "master.mp4",
        "share.mp4",
        str(tmp_path / "missing.srt"),
        str(tmp_path / "missing.txt"),
    )
    assert facts["duration_ok"] is False
    assert facts["coverage"] is False
    assert facts["universal_ok"] is False
    assert facts["caption_ok"] is False
    assert facts["spoken_ok"] is False


def test_rescue_inspector_rejects_empty_artifact_list_as_not_verified(tmp_path):
    """S-06: empty artifact list must never claim all_present=True and all_matching=True."""
    from kinocut.rescue.inspector import inspect_rescue

    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "receipt_kind": "rescue_plan",
                "tool": "video_rescue_plan",
                "status": "ok",
                "source": {},
            }
        ),
        encoding="utf-8",
    )
    inspected = inspect_rescue(str(plan))
    assert inspected["integrity"]["all_present"] is False
    assert inspected["integrity"]["all_matching"] is False


def test_cli_out_prints_string_returning_formatters(capsys):
    """S-09: _out must emit non-None return strings from text formatters."""
    from kinocut.cli.runner import _out

    _out({"frame": 50}, False, lambda res: f"frame={res['frame']}")
    assert capsys.readouterr().out.strip() == "frame=50"


def test_compare_quality_parses_infinite_psnr_as_high():
    """S-10: FFmpeg PSNR average:inf on identical videos must report a JSON-safe perfect metric."""
    from kinocut.engine_compare_quality import _overall_quality, _parse_metric

    computed: dict[str, float] = {}
    _parse_metric("PSNR y:inf u:inf v:inf average:inf min:inf max:inf", "psnr", computed)
    assert computed["psnr"] == 100.0
    assert _overall_quality(computed) == "high"


def test_c2pa_signing_requires_c2patool_in_capability_report():
    """S-11: empty diagnostics must not report c2pa_signing as available."""
    from kinocut.capability_report import capability_report

    reports = {r.capability_id: r for r in capability_report({"checks": []})}
    assert reports["c2pa_signing"].availability == "unavailable"


def test_design_guardrails_flags_invalid_color_instead_of_clean():
    """S-13: invalid color hex must produce an invalid_color warning, not clean=True."""
    from kinocut.design_guardrails import TextOverlaySpec, validate_text_layout

    warnings = validate_text_layout([TextOverlaySpec(text="Hello", position="center", size=48, color="#GGGGGG")])
    assert any(w.code == "invalid_color" for w in warnings)


def test_sound_load_plan_json_rejects_whitespace():
    """S-15: whitespace --plan-json must fail closed instead of running sample demo."""
    from kinocut.cli.handlers_sound import _load_plan_json

    assert _load_plan_json(None) is None
    with pytest.raises(MCPVideoError, match="empty or whitespace"):
        _load_plan_json("   ")


def test_reverse_enforces_uncompressed_memory_budget():
    """V-02: reverse must refuse inputs whose decoded frame buffer exceeds MAX_REVERSE_FRAME_BYTES."""
    from kinocut.engine_reverse import _enforce_reverse_memory_budget

    huge = SimpleNamespace(width=3840, height=2160, duration=600.0, fps=60.0)
    with pytest.raises(MCPVideoError) as exc:
        _enforce_reverse_memory_budget(huge)
    assert exc.value.code == "reverse_memory_limit"


def test_svt_av1_preset_maps_x264_names_to_integers():
    """V-03: _convert_av1 must translate x264 preset strings into numeric libsvtav1 presets."""
    from kinocut.engine_convert import _svt_av1_preset

    assert _svt_av1_preset("fast") == "8"
    assert _svt_av1_preset("slow") == "5"
    assert _svt_av1_preset("6") == "6"


def test_probe_cache_reuses_inode_entry_across_rename(tmp_path):
    """V-05: probing staged path then published path on same inode must hit cache with updated path."""
    from kinocut.engine_probe import _cache_info, _cache_key, _cached_info
    from kinocut.models import VideoInfo

    staged = tmp_path / ".staged.mp4"
    staged.write_bytes(b"abc123")
    key = _cache_key(str(staged))
    info = VideoInfo(path=str(staged), duration=1.0, width=64, height=64, fps=10.0, codec="h264", size_bytes=6)
    _cache_info(str(staged), key, info, has_video=True)

    final = tmp_path / "final.mp4"
    staged.rename(final)
    hit = _cached_info(str(final), _cache_key(str(final)), require_video=True)
    assert hit is not None
    assert hit.path == str(final)
