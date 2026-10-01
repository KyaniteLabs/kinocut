"""Bounded semantic provider worker fixtures; no real paid API requests."""

import json
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_VISION_SAMPLE_FRAMES, MAX_VISION_KEYFRAME_BYTES
from kinocut.watching import vision_provider, vision_qc


@pytest.fixture(autouse=True)
def no_default_paid_requests(monkeypatch):
    monkeypatch.delenv("KINOCUT_VISION_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.mark.parametrize(
    "times",
    [
        [],
        [True],
        ["1"],
        [float("nan")],
        [float("inf")],
        [10**1000],
        [-(10**1000)],
        [-1],
        [14401],
        [0, 0],
        list(range(MAX_VISION_SAMPLE_FRAMES + 1)),
    ],
)
def test_invalid_sample_times_rejected_before_sampling(tmp_path, monkeypatch, times):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(vision_qc, "_sample_keyframes", lambda *args: pytest.fail("invalid samples reached decoder"))
    with pytest.raises(MCPVideoError):
        vision_qc.run_vision_qc(str(source), sample_times=times)


def _fake_worker(monkeypatch, payload, *, stop_reason="end_turn", failure=None):
    from kinocut import ffmpeg_helpers
    from pathlib import Path
    import stat

    calls = []

    def run(cmd, **kwargs):
        request = Path(cmd[-1])
        calls.append(
            {
                "worker_options": kwargs,
                "request_path": str(request),
                "permission_mode": stat.S_IMODE(request.stat().st_mode),
            }
        )
        calls.append(json.loads(request.read_text()))
        if failure:
            raise failure
        return SimpleNamespace(
            stdout=json.dumps({"stop_reason": stop_reason, "content": [{"type": "text", "text": payload}]})
        )

    monkeypatch.setattr(ffmpeg_helpers, "_run_command", run)
    return calls


def _sample(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"safe fake JPEG bytes")
    return [{"time": 0.5, "path": str(frame)}]


def test_provider_executes_one_bounded_request_with_no_retries(tmp_path, monkeypatch):
    payload = json.dumps(
        {
            "verdict": "warn",
            "summary": "Visible text artifact",
            "findings": [{"time": 0.5, "severity": "warn", "message": "Clipped caption"}],
        }
    )
    calls = _fake_worker(monkeypatch, payload)
    result = vision_provider.assess_keyframes("explicit-model", _sample(tmp_path))
    assert result.verdict == "warn"
    assert calls[0]["worker_options"] == {"timeout": 60, "stdout_limit": 65536}
    assert calls[1]["max_tokens"] == 1024
    import os

    if os.name == "posix":
        assert calls[0]["permission_mode"] == 0o600
    from pathlib import Path

    assert not Path(calls[0]["request_path"]).exists()
    assert len([call for call in calls if "messages" in call]) == 1


@pytest.mark.parametrize(
    "payload,stop",
    [
        ("not JSON", "end_turn"),
        ("{}", "end_turn"),
        (
            json.dumps(
                {
                    "verdict": "pass",
                    "summary": "ok",
                    "findings": [{"time": 0.5, "severity": "fail", "message": "Broken"}],
                }
            ),
            "end_turn",
        ),
        (
            json.dumps(
                {
                    "verdict": "fail",
                    "summary": "broken",
                    "findings": [{"time": 8.0, "severity": "fail", "message": "Broken"}],
                }
            ),
            "end_turn",
        ),
        (json.dumps({"verdict": "pass", "summary": "ok", "findings": []}), "max_tokens"),
    ],
)
def test_bad_response_fails_closed(tmp_path, monkeypatch, payload, stop):
    from pydantic import ValidationError

    _fake_worker(monkeypatch, payload, stop_reason=stop)
    with pytest.raises((MCPVideoError, ValidationError)):
        vision_provider.assess_keyframes("explicit-model", _sample(tmp_path))


def test_oversized_frame_rejected_before_worker_creation(tmp_path, monkeypatch):
    calls = _fake_worker(monkeypatch, "{}")
    sample = _sample(tmp_path)
    from pathlib import Path

    Path(sample[0]["path"]).write_bytes(b"x" * (MAX_VISION_KEYFRAME_BYTES + 1))
    with pytest.raises(MCPVideoError):
        vision_provider.assess_keyframes("explicit-model", sample)
    assert calls == []


@pytest.mark.parametrize("time", [10**1000, -(10**1000), float("nan"), True])
def test_direct_provider_rejects_invalid_frame_timestamp_before_worker_creation(tmp_path, monkeypatch, time):
    calls = _fake_worker(monkeypatch, "{}")
    sample = _sample(tmp_path)
    sample[0]["time"] = time
    with pytest.raises(MCPVideoError):
        vision_provider.assess_keyframes("explicit-model", sample)
    assert not calls


@pytest.mark.parametrize("verdict", ["pass", "warn", "fail", "inconclusive"])
def test_configured_provider_result_is_sampled_evidence_not_film_acceptance(tmp_path, monkeypatch, verdict):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setenv("KINOCUT_VISION_MODEL", "explicit-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)
    monkeypatch.setattr(vision_qc, "_sample_keyframes", lambda *args: _sample(tmp_path))
    _fake_worker(monkeypatch, json.dumps({"verdict": verdict, "summary": "fixture assessment", "findings": []}))
    result = vision_qc.run_vision_qc(str(source), sample_times=[0.5], require_vlm=True)
    assert result["verdict"] == verdict
    assert result["assessment_status"] == "evaluated_sampled_frames"
    assert result["whole_film_acceptance"] == "not_granted"
    assert result["blocked"] == (verdict in {"fail", "inconclusive"})


def test_provider_failure_redacts_messages_and_never_passes(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setenv("KINOCUT_VISION_MODEL", "explicit-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)
    monkeypatch.setattr(vision_qc, "_sample_keyframes", lambda *args: _sample(tmp_path))
    calls = _fake_worker(monkeypatch, "{}", failure=TimeoutError("private-key-token"))
    result = vision_qc.run_vision_qc(str(source), sample_times=[0.5], require_vlm=True)
    assert result["verdict"] == "fail"
    assert result["reason"] == "provider_assessment_failed"
    assert "private-key-token" not in json.dumps(result)
    from pathlib import Path

    assert not Path(calls[0]["request_path"]).exists()


def test_source_replacement_invalidates_provider_pass(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setenv("KINOCUT_VISION_MODEL", "explicit-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setattr(vision_qc, "_vlm_package_installed", lambda: False)

    def sampling(*args):
        source.write_bytes(b"replacement")
        return _sample(tmp_path)

    monkeypatch.setattr(vision_qc, "_sample_keyframes", sampling)
    _fake_worker(monkeypatch, json.dumps({"verdict": "pass", "summary": "ok", "findings": []}))
    result = vision_qc.run_vision_qc(str(source), sample_times=[0.5], require_vlm=True)
    assert result["verdict"] == "fail"
    assert result["reason"] == "source_changed_during_assessment"


@pytest.mark.parametrize("trickle", [False, True])
def test_hard_worker_deadline_bounds_hanging_or_trickling_response_and_cleans_request(tmp_path, monkeypatch, trickle):
    import sys
    import time
    from pathlib import Path
    from kinocut import ffmpeg_helpers

    original = ffmpeg_helpers._run_command
    paths = []
    script = (
        "import time; time.sleep(60)"
        if not trickle
        else "import sys,time\nwhile True:\n sys.stdout.write('x');sys.stdout.flush();time.sleep(0.02)"
    )

    def local_hang(cmd, **kwargs):
        paths.append(cmd[-1])
        return original([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(ffmpeg_helpers, "_run_command", local_hang)
    monkeypatch.setattr(vision_provider, "DEFAULT_VISION_PROVIDER_TIMEOUT", 0.2)
    started = time.monotonic()
    with pytest.raises(MCPVideoError):
        vision_provider.assess_keyframes("explicit-model", _sample(tmp_path))
    assert time.monotonic() - started < 5
    assert len(paths) == 1 and not Path(paths[0]).exists()
