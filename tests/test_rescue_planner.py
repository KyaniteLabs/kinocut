"""Deterministic and path-private rescue planning."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue.planner import plan_rescue, read_plan


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_plan_hash_is_deterministic_and_path_private(tmp_path, sample_video):
    source = tmp_path / "incoming" / "clip.mp4"
    source.parent.mkdir()
    shutil.copy2(sample_video, source)

    first = plan_rescue(str(source), str(tmp_path / "out"))
    second = plan_rescue(str(source), str(tmp_path / "out"))

    assert first["plan_sha256"] == second["plan_sha256"]
    assert first["source"]["path"] == "incoming/clip.mp4"
    assert str(Path.home()) not in json.dumps(first)


def test_plan_is_read_only_except_declared_artifacts(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)
    source_hash = _sha256(source)

    plan = plan_rescue(
        str(source),
        str(tmp_path / "out"),
        save_plan=str(tmp_path / "out" / "plan.json"),
    )

    assert _sha256(source) == source_hash
    assert {path.name for path in (tmp_path / "out").iterdir()} == {"plan.json", "previews"}
    assert plan["status"] == "planned"
    assert read_plan(tmp_path / "out" / "plan.json").plan_sha256 == plan["plan_sha256"]


def test_read_plan_rejects_tampered_action_fields(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)
    plan_path = tmp_path / "out" / "plan.json"
    plan_rescue(str(source), str(plan_path.parent), save_plan=str(plan_path))
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["package_intents"][0]["required"] = False
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MCPVideoError) as caught:
        read_plan(plan_path)

    assert caught.value.code == "rescue_plan_mismatch"


def test_save_plan_must_stay_inside_output_dir(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(
            str(source),
            str(tmp_path / "out"),
            save_plan=str(tmp_path / "elsewhere" / "plan.json"),
        )

    assert caught.value.code == "unsafe_rescue_output"
    assert not (tmp_path / "out").exists()


def test_unsupported_policy_fails_before_artifacts_are_created(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(str(source), str(tmp_path / "out"), policy_id="cloud_magic")

    assert caught.value.code == "rescue_policy_violation"
    assert not (tmp_path / "out").exists()
