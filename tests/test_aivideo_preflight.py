"""Tests for the unified media preflight report (Plan 01 Task 6).

The preflight composes the shipped inspection engines — ``engine_probe`` for the
technical metadata, ``VisualQualityGuardrails`` for loudness and color, and a
full-decode pass for integrity — into ONE typed :class:`PreflightReport`. Missing
audio is stated explicitly (``has_audio=False`` with the loudness measurements
absent, never a zero-loudness lie). The report is stored as a deterministic,
content-addressed, private artifact inside the project store, and the owning
:class:`AssetRecord` is *superseded* by an append-only record that references the
artifact — the original record and the original media bytes are never mutated.
Every malformed-probe / decode failure surfaces as a stable, privacy-safe
:class:`MCPVideoError` that echoes no host path and no raw FFmpeg stderr.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut import quality_guardrails
from kinocut.aivideo import preflight
from kinocut.aivideo.ingest import ingest_project_asset
from kinocut.aivideo.preflight import (
    IntegrityInfo,
    PreflightReport,
    TechnicalInfo,
    build_preflight_report,
    run_preflight,
)
from kinocut.contracts.asset import AssetRecord
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError
from kinocut.models import VideoInfo
from kinocut.projectstore import open_project, read_records
from kinocut.quality_guardrails import VisualQualityGuardrails
from kinocut.quality_guardrails import QualityReport

_HAS_FFPROBE = shutil.which("ffprobe") is not None


def _asset_digest_dir(project_root: Path, asset_id: str) -> Path:
    return project_root / ".kinocut" / "assets" / "sha256" / asset_id.split(":", 1)[1]


def _artifact_digest_dir(project_root: Path, artifact_id: str) -> Path:
    return project_root / ".kinocut" / "artifacts" / "sha256" / artifact_id.split(":", 1)[1]


def test_report_captures_technical_streams_and_geometry(sample_video):
    report = build_preflight_report(sample_video)
    assert isinstance(report, PreflightReport)
    tech = report.technical
    # Streams + codecs are enumerated (video + audio for the sine-audio fixture).
    codec_types = {s.codec_type for s in tech.streams}
    assert "video" in codec_types
    assert "audio" in codec_types
    assert tech.video_codec  # non-empty codec name
    # Display dimensions, fps, rotation, duration come straight off the probe.
    assert (tech.width, tech.height) == (640, 480)
    assert abs(tech.fps - 30.0) < 1.0
    assert tech.rotation == 0
    assert abs(tech.duration - 3.0) < 0.5


def test_report_captures_loudness_for_audio(sample_video):
    loud = build_preflight_report(sample_video).loudness
    assert loud.has_audio is True
    assert isinstance(loud.integrated_lufs, float)
    assert isinstance(loud.true_peak_dbtp, float)
    assert loud.integrated_lufs < 0.0  # LUFS of real audio is negative


def test_missing_audio_is_explicit_and_never_zero_loudness(sample_video_no_audio):
    loud = build_preflight_report(sample_video_no_audio).loudness
    assert loud.has_audio is False
    # Absent, NOT a zero-loudness lie.
    assert loud.integrated_lufs is None
    assert loud.true_peak_dbtp is None


def test_report_includes_color(sample_video):
    color = build_preflight_report(sample_video).color
    assert color.analyzed is True
    assert isinstance(color.r_mean, float)
    assert isinstance(color.g_mean, float)
    assert isinstance(color.b_mean, float)


def test_full_decode_integrity_passes_for_valid_media(sample_video):
    integrity = build_preflight_report(sample_video).integrity
    assert integrity.fully_decoded is True
    assert integrity.decode_error_count == 0


@pytest.mark.skipif(not _HAS_FFPROBE, reason="ffprobe not installed")
def test_malformed_input_raises_private_error(tmp_path):
    bad = tmp_path / "not-a-real-video.mp4"
    bad.write_bytes(b"\x00\x01garbage-not-a-container\x02\x03" * 8)
    with pytest.raises(MCPVideoError) as exc:
        build_preflight_report(str(bad))
    message = str(exc.value)
    # No host path and no raw FFmpeg stderr may leak through the boundary.
    assert str(tmp_path) not in message
    assert str(Path.home()) not in message
    assert "not-a-real-video.mp4" not in message


def test_run_preflight_stores_artifact_and_supersedes_without_mutation(tmp_path, sample_video):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    digest_dir = _asset_digest_dir(proj.root, original.asset_id)
    stored_media = next(p for p in digest_dir.iterdir() if p.suffix == ".mp4")
    media_bytes = stored_media.read_bytes()

    enriched = run_preflight(proj, original)

    # The superseding record references a content-addressed preflight artifact.
    assert isinstance(enriched, AssetRecord)
    assert enriched.supersedes == original.record_id
    assert enriched.preflight_artifact_id is not None
    assert enriched.preflight_artifact_id.startswith("sha256:")

    # The artifact is stored privately and is content-addressed (deterministic).
    artifact = _artifact_digest_dir(proj.root, enriched.preflight_artifact_id) / "preflight.json"
    assert artifact.is_file()
    on_disk_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert enriched.preflight_artifact_id.split(":", 1)[1] == on_disk_digest

    # Append-only: the original record and the original bytes are untouched.
    records = read_records(proj, "asset_record")
    assert len(records) == 2
    prior = next(r for r in records if r.record_id == original.record_id)
    assert prior.preflight_artifact_id is None
    assert stored_media.read_bytes() == media_bytes


def test_stored_artifact_and_record_leak_no_host_path(tmp_path, sample_video):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    enriched = run_preflight(proj, original)
    artifact = _artifact_digest_dir(proj.root, enriched.preflight_artifact_id) / "preflight.json"
    blob = artifact.read_text(encoding="utf-8")
    assert str(Path.home()) not in blob
    assert str(tmp_path) not in blob
    assert str(tmp_path) not in enriched.model_dump_json()


# ---------------------------------------------------------------------------
# Defect 1 — rotated media must report DISPLAY dimensions, not coded ones.
# ffprobe reports 1920x1080 coded pixels for portrait phone video with a 90°
# rotation side-datum; the truthful width/height a human sees are swapped. The
# report must fold in the shipped ``info.display_width`` / ``info.display_height``.
# ---------------------------------------------------------------------------

_STUB_RAW_STREAMS = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264"},
        {"index": 1, "codec_type": "audio", "codec_name": "aac"},
    ]
}


def _stub_probe(rotation: int) -> VideoInfo:
    """A VideoInfo with coded 1920x1080 and the given rotation side-datum."""
    return VideoInfo(
        path="stub",
        duration=4.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        audio_codec="aac",
        rotation=rotation,
    )


@pytest.mark.parametrize("rotation", [90, 270])
def test_technical_reports_display_dimensions_for_rotated_media(monkeypatch, rotation):
    monkeypatch.setattr(preflight, "probe", lambda _p: _stub_probe(rotation))
    monkeypatch.setattr(preflight, "_run_ffprobe_json", lambda _p: _STUB_RAW_STREAMS)
    tech = preflight._technical("ignored")
    # Coded is 1920x1080; a 90°/270° rotation swaps them for the viewer.
    assert (tech.width, tech.height) == (1080, 1920)
    assert tech.rotation == rotation


def test_technical_keeps_coded_dimensions_when_unrotated(monkeypatch):
    monkeypatch.setattr(preflight, "probe", lambda _p: _stub_probe(0))
    monkeypatch.setattr(preflight, "_run_ffprobe_json", lambda _p: _STUB_RAW_STREAMS)
    tech = preflight._technical("ignored")
    assert (tech.width, tech.height) == (1920, 1080)


# ---------------------------------------------------------------------------
# Defect 2 — the privacy boundary must wrap ALL of technical assembly. A
# malformed stream index (raw ``ValueError``) and an unexpected raw probe
# ``RuntimeError`` must both collapse to the stable typed error, leaking no
# unique marker, host path, or FFmpeg stderr.
# ---------------------------------------------------------------------------

_MARKER_BAD_INDEX = "KYANITE_MARKER_BAD_STREAM_INDEX_9f3c"
_MARKER_RAW_RUNTIME = "KYANITE_MARKER_RAW_PROBE_RUNTIME_a71b"
_MARKER_HOST_PATH = "/private/host/secret/KYANITE_MARKER_HOST_PATH"
_MARKER_STDERR = "KYANITE_MARKER_FFMPEG_STDERR_LEAK"


def test_malformed_stream_index_maps_to_typed_probe_error(monkeypatch):
    monkeypatch.setattr(preflight, "probe", lambda _p: _stub_probe(0))
    monkeypatch.setattr(
        preflight,
        "_run_ffprobe_json",
        lambda _p: {"streams": [{"index": _MARKER_BAD_INDEX, "codec_type": "video"}]},
    )
    with pytest.raises(MCPVideoError) as exc:
        preflight._technical(_MARKER_HOST_PATH)
    assert exc.value.code == "preflight_probe_failed"
    message = str(exc.value)
    # The raw ValueError carries the bad marker value; it must not leak out.
    assert _MARKER_BAD_INDEX not in message
    assert _MARKER_HOST_PATH not in message


def test_unexpected_raw_probe_runtime_maps_to_typed_probe_error(monkeypatch):
    def _boom(_p):
        raise RuntimeError(f"{_MARKER_RAW_RUNTIME} {_MARKER_HOST_PATH}\n{_MARKER_STDERR}")

    monkeypatch.setattr(preflight, "probe", _boom)
    monkeypatch.setattr(preflight, "_run_ffprobe_json", lambda _p: _STUB_RAW_STREAMS)
    with pytest.raises(MCPVideoError) as exc:
        preflight._technical(_MARKER_HOST_PATH)
    assert exc.value.code == "preflight_probe_failed"
    message = str(exc.value)
    # A bare RuntimeError (not an MCPVideoError) must not escape, nor its content.
    assert _MARKER_RAW_RUNTIME not in message
    assert _MARKER_HOST_PATH not in message
    assert _MARKER_STDERR not in message


# ---------------------------------------------------------------------------
# Defect 3 — ``_has_audio_stream`` returning None is an INDETERMINATE probe
# failure, not confirmed-absent audio. None must raise the stable typed error;
# only an explicit False is "no audio" with None measurements.
# ---------------------------------------------------------------------------


def test_indeterminate_audio_probe_raises_typed_error(monkeypatch):
    guard = VisualQualityGuardrails()
    monkeypatch.setattr(guard, "_has_audio_stream", lambda _p: None)
    with pytest.raises(MCPVideoError) as exc:
        preflight._loudness(guard, _MARKER_HOST_PATH)
    assert exc.value.code == "preflight_probe_failed"
    assert _MARKER_HOST_PATH not in str(exc.value)


def test_confirmed_absent_audio_stays_has_audio_false(monkeypatch):
    guard = VisualQualityGuardrails()
    monkeypatch.setattr(guard, "_has_audio_stream", lambda _p: False)
    loud = preflight._loudness(guard, "ignored")
    assert loud.has_audio is False
    # Absent, never a fabricated zero-loudness measurement.
    assert loud.integrated_lufs is None
    assert loud.true_peak_dbtp is None


@pytest.mark.parametrize(
    ("rotation", "normalized"),
    [(-90, 270), (-270, 90), (450, 90)],
)
def test_negative_and_wrapped_rotations_use_normalized_display_geometry(monkeypatch, rotation, normalized):
    info = _stub_probe(rotation)
    assert info.normalized_rotation == normalized
    assert (info.display_width, info.display_height) == (1080, 1920)

    monkeypatch.setattr(preflight, "probe", lambda _p: info)
    monkeypatch.setattr(preflight, "_run_ffprobe_json", lambda _p: _STUB_RAW_STREAMS)
    tech = preflight._technical("ignored")
    assert (tech.width, tech.height) == (1080, 1920)
    assert tech.rotation == normalized


@pytest.mark.parametrize("value", ["-inf", "+inf", "nan", float("inf")])
def test_loudness_nonfinite_measurements_are_explicitly_absent(monkeypatch, value):
    guard = VisualQualityGuardrails()
    monkeypatch.setattr(guard, "_has_audio_stream", lambda _p: True)
    monkeypatch.setattr(
        guard,
        "_analyze_loudnorm",
        lambda _p: {"input_i": value, "input_tp": value},
    )
    loud = preflight._loudness(guard, "ignored")
    assert loud.has_audio is True
    assert loud.integrated_lufs is None
    assert loud.true_peak_dbtp is None


def test_decode_input_file_error_maps_to_private_stable_error(monkeypatch):
    def _boom(_args):
        raise InputFileError(_MARKER_HOST_PATH, _MARKER_STDERR)

    monkeypatch.setattr(preflight, "_run_ffmpeg", _boom)
    with pytest.raises(MCPVideoError) as exc:
        preflight._integrity(_MARKER_HOST_PATH)
    assert exc.value.error_type == "input_error"
    assert exc.value.code == "preflight_decode_failed"
    assert _MARKER_HOST_PATH not in str(exc.value)
    assert _MARKER_STDERR not in str(exc.value)


def test_input_validation_maps_to_private_stable_error(monkeypatch):
    def _boom(_path):
        raise InputFileError(_MARKER_HOST_PATH, _MARKER_STDERR)

    monkeypatch.setattr(preflight, "_validate_input_path", _boom)
    with pytest.raises(MCPVideoError) as exc:
        build_preflight_report(_MARKER_HOST_PATH)
    assert exc.value.error_type == "input_error"
    assert exc.value.code == "preflight_input_failed"
    assert _MARKER_HOST_PATH not in str(exc.value)
    assert _MARKER_STDERR not in str(exc.value)


def test_probe_warning_logs_exception_type_without_sensitive_content(monkeypatch, caplog):
    def _boom(_p):
        raise RuntimeError(f"{_MARKER_RAW_RUNTIME} {_MARKER_HOST_PATH} {_MARKER_STDERR}")

    monkeypatch.setattr(preflight, "probe", _boom)
    with caplog.at_level("WARNING", logger=preflight.__name__), pytest.raises(MCPVideoError) as exc:
        preflight._technical(_MARKER_HOST_PATH)
    assert exc.value.error_type == "input_error"
    assert exc.value.code == "preflight_probe_failed"
    log_text = caplog.text
    assert "RuntimeError" in log_text
    assert _MARKER_RAW_RUNTIME not in log_text
    assert _MARKER_HOST_PATH not in log_text
    assert _MARKER_STDERR not in log_text


def test_build_preflight_loudness_failure_logs_no_path_or_raw_error(monkeypatch, caplog):
    monkeypatch.setattr(preflight, "_validate_input_path", lambda _path: _MARKER_HOST_PATH)
    monkeypatch.setattr(
        preflight,
        "_technical",
        lambda _path: TechnicalInfo(
            streams=(),
            video_codec="h264",
            width=640,
            height=480,
            fps=30.0,
            rotation=0,
            duration=1.0,
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_integrity",
        lambda _path: IntegrityInfo(fully_decoded=True, decode_error_count=0),
    )
    monkeypatch.setattr(VisualQualityGuardrails, "_has_audio_stream", lambda _self, _path: True)
    monkeypatch.setattr(
        VisualQualityGuardrails,
        "check_color_balance",
        lambda _self, _path: QualityReport("color", True, 100.0, "ok"),
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError(f"{_MARKER_HOST_PATH} {_MARKER_STDERR}")

    monkeypatch.setattr(quality_guardrails.subprocess, "run", _boom)
    with caplog.at_level("WARNING", logger=quality_guardrails.__name__):
        build_preflight_report(_MARKER_HOST_PATH)
    assert _MARKER_HOST_PATH not in caplog.text
    assert _MARKER_STDERR not in caplog.text


@pytest.mark.parametrize("fault", ["no_json", "timeout", "invalid_json"])
def test_loudness_fallback_logs_no_host_path(monkeypatch, caplog, fault):
    guard = VisualQualityGuardrails()

    def _run(*_args, **_kwargs):
        if fault == "timeout":
            raise quality_guardrails.subprocess.TimeoutExpired("ffmpeg", 1)
        stderr = "not-json" if fault == "no_json" else "{malformed}"
        return SimpleNamespace(stderr=stderr)

    monkeypatch.setattr(quality_guardrails.subprocess, "run", _run)
    with caplog.at_level("WARNING", logger=quality_guardrails.__name__):
        result = guard._analyze_loudnorm(_MARKER_HOST_PATH)
    assert "_error" in result
    assert _MARKER_HOST_PATH not in caplog.text


def test_audio_stream_probe_failure_logs_no_path_or_raw_stderr(monkeypatch, caplog):
    guard = VisualQualityGuardrails()

    def _boom(_path):
        raise ProcessingError("ffprobe", 1, _MARKER_STDERR)

    monkeypatch.setattr(quality_guardrails, "_run_ffprobe_json", _boom)
    with caplog.at_level("WARNING", logger=quality_guardrails.__name__):
        assert guard._has_audio_stream(_MARKER_HOST_PATH) is None
    assert _MARKER_HOST_PATH not in caplog.text
    assert _MARKER_STDERR not in caplog.text


@pytest.mark.parametrize(
    "fault",
    ["nonzero", "no_frames", "incomplete", "timeout", "invalid_json", "exception"],
)
def test_color_analysis_failure_logs_no_path_or_raw_stderr(monkeypatch, caplog, fault):
    guard = VisualQualityGuardrails()

    def _run(*_args, **_kwargs):
        if fault == "timeout":
            raise quality_guardrails.subprocess.TimeoutExpired("ffprobe", 1)
        if fault == "exception":
            raise RuntimeError(_MARKER_STDERR)
        if fault == "nonzero":
            return SimpleNamespace(returncode=1, stderr=_MARKER_STDERR, stdout="")
        if fault == "invalid_json":
            return SimpleNamespace(returncode=0, stderr="", stdout="{malformed}")
        frames = [] if fault == "no_frames" else [{"tags": {}}]
        return SimpleNamespace(returncode=0, stderr="", stdout=str({"frames": frames}).replace("'", '"'))

    monkeypatch.setattr(quality_guardrails.subprocess, "run", _run)
    with caplog.at_level("WARNING", logger=quality_guardrails.__name__):
        result = guard._get_rgb_means(_MARKER_HOST_PATH)
    assert result is not None and "_error" in result
    assert _MARKER_HOST_PATH not in caplog.text
    assert _MARKER_STDERR not in caplog.text


def test_run_preflight_rejects_unpersisted_asset_before_probe(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    unpersisted = original.model_copy(update={"record_id": None})
    called = False

    def _unexpected(_path):
        nonlocal called
        called = True
        raise AssertionError("preflight must reject before probing")

    monkeypatch.setattr(preflight, "build_preflight_report", _unexpected)
    with pytest.raises(MCPVideoError) as exc:
        run_preflight(proj, unpersisted)
    assert called is False
    assert exc.value.error_type == "validation_error"
    assert exc.value.code == "preflight_asset_unpersisted"


def test_run_preflight_rejects_caller_record_that_differs_from_persisted_asset(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    forged = original.model_copy(update={"byte_size": original.byte_size + 1})

    def _unexpected(_path):
        raise AssertionError("preflight must authenticate the record before probing")

    monkeypatch.setattr(preflight, "build_preflight_report", _unexpected)
    with pytest.raises(MCPVideoError) as exc:
        run_preflight(proj, forged)
    assert exc.value.error_type == "validation_error"
    assert exc.value.code == "preflight_asset_mismatch"


def test_append_failure_removes_newly_created_preflight_artifact(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    report = build_preflight_report(sample_video)
    artifact_id, _ = preflight._canonical_artifact(report)
    artifact = _artifact_digest_dir(proj.root, artifact_id) / "preflight.json"
    assert not artifact.exists()
    monkeypatch.setattr(preflight, "build_preflight_report", lambda _path: report)

    def _append_fails(_project, _record):
        raise MCPVideoError("append failed", error_type="store_error", code="append_failed")

    monkeypatch.setattr(preflight.store, "append_record_locked", _append_fails)
    with pytest.raises(MCPVideoError, match="append failed"):
        run_preflight(proj, original)
    assert not artifact.exists()


def test_append_failure_preserves_preexisting_content_addressed_artifact(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    report = build_preflight_report(sample_video)
    artifact_id, line = preflight._canonical_artifact(report)
    artifact = _artifact_digest_dir(proj.root, artifact_id) / "preflight.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(line, encoding="utf-8")
    monkeypatch.setattr(preflight, "build_preflight_report", lambda _path: report)

    def _append_fails(_project, _record):
        raise MCPVideoError("append failed", error_type="store_error", code="append_failed")

    monkeypatch.setattr(preflight.store, "append_record_locked", _append_fails)
    with pytest.raises(MCPVideoError, match="append failed"):
        run_preflight(proj, original)
    assert artifact.read_text(encoding="utf-8") == line


def test_run_preflight_refuses_preexisting_artifact_with_different_bytes(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    report = build_preflight_report(sample_video)
    artifact_id, _ = preflight._canonical_artifact(report)
    artifact = _artifact_digest_dir(proj.root, artifact_id) / "preflight.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    hostile = b"hostile preexisting bytes"
    artifact.write_bytes(hostile)
    monkeypatch.setattr(preflight, "build_preflight_report", lambda _path: report)

    with pytest.raises(MCPVideoError) as exc:
        run_preflight(proj, original)
    assert exc.value.error_type == "store_error"
    assert exc.value.code == "preflight_artifact_mismatch"
    assert artifact.read_bytes() == hostile
    assert len(read_records(proj, "asset_record")) == 1


def test_artifact_install_and_record_append_hold_one_project_lock(tmp_path, sample_video, monkeypatch):
    proj = open_project(tmp_path / "proj")
    original = ingest_project_asset(proj, sample_video)
    report = build_preflight_report(sample_video)
    monkeypatch.setattr(preflight, "build_preflight_report", lambda _path: report)
    real_install = preflight._install_or_verify_artifact
    install_entered = threading.Event()
    allow_install = threading.Event()
    contender_acquired = threading.Event()
    failures: list[BaseException] = []

    def _paused_install(path, line):
        install_entered.set()
        assert allow_install.wait(timeout=2)
        return real_install(path, line)

    def _run():
        try:
            run_preflight(proj, original)
        except BaseException as exc:  # test thread must report every failure
            failures.append(exc)

    def _contend():
        with preflight.store._project_lock(proj):
            contender_acquired.set()

    monkeypatch.setattr(preflight, "_install_or_verify_artifact", _paused_install)
    runner = threading.Thread(target=_run)
    runner.start()
    assert install_entered.wait(timeout=2)
    contender = threading.Thread(target=_contend)
    contender.start()
    try:
        assert not contender_acquired.wait(timeout=0.2)
    finally:
        allow_install.set()
        runner.join(timeout=3)
        contender.join(timeout=3)
    assert not failures
    assert not runner.is_alive()
    assert not contender.is_alive()
