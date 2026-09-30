"""Vision evidence preparation must never masquerade as an analyzer pass."""

import importlib.util

import pytest

from kinocut.watching import vision_qc


@pytest.mark.parametrize("package_installed", [False, True])
@pytest.mark.parametrize("sampled", [0, 1, 3])
@pytest.mark.parametrize("required", [False, True])
def test_assessment_reports_unavailable_executor_independently_of_sdk(
    tmp_path, monkeypatch, package_installed, sampled, required,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if package_installed else None)
    keyframes = [
        {"time": time, "path": str(tmp_path / f"frame{i}.jpg") if i < sampled else None}
        for i, time in enumerate([0.5, 1.0, 2.0])
    ]
    monkeypatch.setattr(vision_qc, "_sample_keyframes", lambda path, times: keyframes)

    result = vision_qc.run_vision_qc(str(source), require_vlm=required)

    assert result["verdict"] == ("fail" if required else "not_evaluated" if sampled == 3 else "inconclusive")
    assert result["assessment_status"] == "not_evaluated"
    assert result["sampling_status"] == ("complete" if sampled == 3 else "partial" if sampled else "unavailable")
    assert result["keyframe_count"] == sampled
    assert result["vlm_available"] is False
    assert result["vlm_package_installed"] is package_installed
    assert result["auto_scored"] is False
    assert result["blocked"] is required
    finding = next(item for item in result["findings"] if item["check_id"] == "vision.vlm")
    assert finding["severity"] == ("fail" if required else "info")
    assert finding["evidence"]["reason"] == "provider_executor_unavailable"


def test_prepared_keyframe_paths_remain_readable_for_deferred_review(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    artifact_dir = tmp_path / "retained"
    artifact_dir.mkdir()
    monkeypatch.setattr(vision_qc.tempfile, "mkdtemp", lambda **kwargs: str(artifact_dir))
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)

    def extract(args):
        from pathlib import Path

        Path(args[-1]).write_bytes(b"sample-jpeg")

    monkeypatch.setattr(vision_qc, "_run_ffmpeg", extract)
    result = vision_qc.run_vision_qc(str(source), sample_times=[0.1])
    keyframes = result["findings"][0]["evidence"]["keyframes"]
    assert result["verdict"] == "not_evaluated"
    assert result["sampling_status"] == "complete"
    from pathlib import Path

    assert Path(keyframes[0]["path"]).read_bytes() == b"sample-jpeg"


def test_public_tool_preserves_inconclusive_assessment(tmp_path, monkeypatch):
    from kinocut.server_tools_intent import video_qc_vision

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(vision_qc, "_sample_keyframes", lambda path, times: [])
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)
    result = video_qc_vision(str(source))
    assert result["success"] is True  # Evidence preparation is not semantic acceptance.
    assert result["verdict"] == "inconclusive"
    assert result["assessment_status"] == "not_evaluated"


def test_failed_frame_extraction_is_inconclusive_without_a_content_pass(tmp_path, monkeypatch):
    from kinocut.errors import ProcessingError

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)

    def failed_extract(args):
        raise ProcessingError("ffmpeg", 1, "could not decode frame")

    monkeypatch.setattr(vision_qc, "_run_ffmpeg", failed_extract)
    result = vision_qc.run_vision_qc(str(source), sample_times=[0.1])
    assert result["verdict"] == "inconclusive"
    assert result["sampling_status"] == "unavailable"
    assert result["findings"][0]["severity"] == "warn"
    assert result["findings"][0]["evidence"]["keyframes"][0]["error"] == "ProcessingError"
