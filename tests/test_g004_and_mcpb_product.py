"""G004 synthetic fixture pack + MCPB production pack product residuals."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kinocut.watching import ReviewPolicy, run_review


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_g004_phone_frame_fixture_and_review(tmp_path: Path) -> None:
    out_dir = tmp_path / "g004"
    proc = subprocess.run(
        [sys.executable, "scripts/make_g004_fixtures.py", "--out-dir", str(out_dir), "--seconds", "6"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    # script names file phone_frame_12s even when seconds overridden — check any mp4
    phones = list(out_dir.glob("*.mp4"))
    assert phones, proc.stdout
    media = phones[0]
    assert media.stat().st_size > 1000
    result = run_review(str(media), ReviewPolicy())
    assert result.to_dict()["artifact_kind"] == "review_run"
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_kind"] == "g004_fixture_pack"


def test_mcpb_production_pack_checklist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "mcpb-prod"
    proc = subprocess.run(
        [sys.executable, "scripts/mcpb_production_pack.py", "--out-dir", str(out), "--skip-build"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    checklist = json.loads((out / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["artifact_kind"] == "mcpb_production_checklist"
    assert checklist["signing"]["status"] == "not_applicable"
    assert (out / "CLEAN_MACHINE.md").is_file()
