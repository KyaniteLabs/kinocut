"""Deterministic and path-private rescue planning."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue.models import RescuePlan, canonical_payload
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


def test_plan_uses_stable_no_audio_reason_for_optional_sidecars(tmp_path, sample_video):
    source = tmp_path / "video-only.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", sample_video, "-an", "-c:v", "copy", str(source)],
        check=True,
    )

    plan = plan_rescue(str(source), str(tmp_path / "out"))

    intents = {item["kind"]: item for item in plan["package_intents"]}
    assert intents["captions"]["reason"] == "no_audio_stream"
    assert intents["transcript"]["reason"] == "no_audio_stream"


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


def test_read_plan_rejects_rehashed_policy_bucket_forgery(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)
    plan_path = tmp_path / "out" / "plan.json"
    plan_rescue(str(source), str(plan_path.parent), save_plan=str(plan_path))
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    forged = payload["unavailable_repairs"].pop(0)
    forged.update({"disposition": "safe_repair", "promotable": True})
    payload["safe_repairs"].append(forged)
    payload["plan_sha256"] = None
    plan = RescuePlan.model_validate(payload)
    payload["plan_sha256"] = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
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


def test_plan_rejects_symlinked_source_entry(tmp_path, sample_video):
    outside = tmp_path.parent / f"outside-{tmp_path.name}.mp4"
    shutil.copy2(sample_video, outside)
    source = tmp_path / "linked-source.mp4"
    source.symlink_to(outside)

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(str(source), str(tmp_path / "out"))

    assert caught.value.code == "unsafe_rescue_output"
    assert not (tmp_path / "out").exists()


def test_unsupported_policy_fails_before_artifacts_are_created(tmp_path, sample_video):
    source = tmp_path / "clip.mp4"
    shutil.copy2(sample_video, source)

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(str(source), str(tmp_path / "out"), policy_id="cloud_magic")

    assert caught.value.code == "rescue_policy_violation"
    assert not (tmp_path / "out").exists()
