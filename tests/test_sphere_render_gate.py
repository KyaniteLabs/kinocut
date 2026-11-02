"""Render-seam fail-closed gate: rejected 360 sources never reach a decode.

Intake (``probe_360_source``) already rejects ``.insv``, raw containers and
non-equirect clips before a plan exists. These tests pin the same rejection
at the render seam: a forged or stale *approved* plan pointing at a rejected
source must fail closed before FFmpeg is invoked — with or without
``allow_fail``, which bypasses the quality gate that used to be the only
barrier.
"""

from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.source_identity import stream_source_identity
from kinocut.te import propose_360_assembly, render_sphere_plan
from kinocut.te import sphere_render


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True, timeout=60)


def _equirect(path: Path) -> str:
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x320:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x320:d=1",
            "-filter_complex",
            "hstack=inputs=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return str(path)


def _flat(path: Path) -> str:
    _run_ffmpeg(["-f", "lavfi", "-i", "color=c=gray:s=640x480:d=1", "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def _forged_approved_plan(source: str, good: str) -> dict:
    plan = propose_360_assembly(good, goal="desk 360 split 9:16")
    forged = deepcopy(plan)
    forged["source"]["path"] = source
    # sha256 deliberately left from the good source: the policy gate must fire
    # before identity is ever compared.
    forged["status"] = "approved"
    return forged


@pytest.fixture()
def no_decode(monkeypatch: pytest.MonkeyPatch) -> list:
    """Fail closed if the render graph is ever built."""
    calls: list = []

    def _boom(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("render graph was invoked for a rejected source")

    monkeypatch.setattr(sphere_render, "render_window_single_pass", _boom)
    return calls


def test_insv_plan_fails_closed_before_decode(tmp_path: Path, no_decode: list) -> None:
    good = _equirect(tmp_path / "sphere.mp4")
    insv = tmp_path / "take.insv"
    insv.write_bytes((tmp_path / "sphere.mp4").read_bytes())  # real mp4 bytes behind a raw suffix
    output = tmp_path / "out.mp4"

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(_forged_approved_plan(str(insv), good), str(output), work_dir=str(tmp_path / "w"))

    assert exc.value.code == "not_insv_export"
    assert "Export a stitched" in str(exc.value)
    assert "Insta360" in str(exc.value)
    assert not output.exists()
    assert no_decode == []


def test_insv_plan_fails_closed_even_with_allow_fail(tmp_path: Path, no_decode: list) -> None:
    good = _equirect(tmp_path / "sphere.mp4")
    insv = tmp_path / "take.insv"
    insv.write_bytes((tmp_path / "sphere.mp4").read_bytes())
    output = tmp_path / "out.mp4"

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(
            _forged_approved_plan(str(insv), good), str(output), work_dir=str(tmp_path / "w"), allow_fail=True
        )

    assert exc.value.code == "not_insv_export"
    assert not output.exists()
    assert no_decode == []


def test_raw_360_container_rejected_at_render(tmp_path: Path, no_decode: list) -> None:
    good = _equirect(tmp_path / "sphere.mp4")
    raw = tmp_path / "take.360"
    raw.write_bytes((tmp_path / "sphere.mp4").read_bytes())

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(_forged_approved_plan(str(raw), good), str(tmp_path / "out.mp4"))

    assert exc.value.code == "not_raw_360"
    assert no_decode == []


def test_flat_source_rejected_at_render_before_decode(tmp_path: Path, no_decode: list) -> None:
    """Identity-consistent forgery: correct sha over a flat, non-360 file.

    Only the seam's geometry gate can catch this — the plan looks perfectly
    healthy to the identity check (intake was bypassed at plan time).
    """
    good = _equirect(tmp_path / "sphere.mp4")
    flat = _flat(tmp_path / "phone.mp4")
    forged = _forged_approved_plan(flat, good)
    forged["source"]["sha256"] = stream_source_identity(flat).asset_id

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(forged, str(tmp_path / "out.mp4"))

    assert exc.value.code == "not_360_equirect"
    assert "Not a 360 equirect source" in str(exc.value)
    assert not (tmp_path / "out.mp4").exists()
    assert no_decode == []


def test_stale_sha_on_flat_source_reports_identity_first(tmp_path: Path, no_decode: list) -> None:
    """Precedence pin: a stale plan is diagnosed as stale before geometry.

    The file behind the plan changed since approval — the actionable recovery
    is replanning, so identity runs before the geometry gate (matching the
    long-standing seam behaviour pinned in test_sphere_source_identity.py).
    """
    good = _equirect(tmp_path / "sphere.mp4")
    flat = _flat(tmp_path / "phone.mp4")

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(_forged_approved_plan(flat, good), str(tmp_path / "out.mp4"))

    assert exc.value.code == "source_identity_changed"
    assert not (tmp_path / "out.mp4").exists()
    assert no_decode == []


def test_policy_gate_precedes_identity_mismatch(tmp_path: Path) -> None:
    """A stale sha on an .insv source still reports the policy code, not identity."""
    good = _equirect(tmp_path / "sphere.mp4")
    insv = tmp_path / "take.insv"
    insv.write_bytes(b"not even a video stream")

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(_forged_approved_plan(str(insv), good), str(tmp_path / "out.mp4"))

    assert exc.value.code == "not_insv_export"


def test_missing_source_fails_closed_at_render(tmp_path: Path, no_decode: list) -> None:
    """A vanished source is wrapped as an identity failure (seam convention)."""
    good = _equirect(tmp_path / "sphere.mp4")

    with pytest.raises(MCPVideoError) as exc:
        render_sphere_plan(_forged_approved_plan(str(tmp_path / "gone.mp4"), good), str(tmp_path / "out.mp4"))
    assert exc.value.code == "source_identity_changed"
    assert "cannot be verified" in str(exc.value)
    assert not (tmp_path / "out.mp4").exists()
    assert no_decode == []


def test_allow_fail_still_renders_a_valid_equirect_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No regression: allow_fail keeps publishing for sources the intake accepts."""
    good = _equirect(tmp_path / "sphere.mp4")
    plan = propose_360_assembly(good, goal="desk 360 split 9:16")
    plan["status"] = "approved"
    output = tmp_path / "out.mp4"

    receipt = render_sphere_plan(plan, str(output), work_dir=str(tmp_path / "w"), allow_fail=True)

    assert output.exists() and output.stat().st_size > 0
    assert receipt["output_path"].endswith("out.mp4")
