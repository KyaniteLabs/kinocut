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
