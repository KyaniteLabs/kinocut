"""Truthful sound evidence and non-executable paid-surface contracts."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from kinocut.errors import MCPVideoError
from kinocut.multipliers import (
    GenerativePlan,
    assert_generative_executable,
    plan_generative_last_mile,
    plan_tts_dub,
)
from kinocut.multipliers import generative, tts_dub
from kinocut.sound_joins.benchmark import DEFAULT_CLIP_COUNT, FixtureSpec


ROOT = Path(__file__).resolve().parents[1]


def _error_code(plan: GenerativePlan | dict[str, Any]) -> str:
    with pytest.raises(MCPVideoError) as exc_info:
        assert_generative_executable(plan)
    return exc_info.value.code


def test_sound_claims_match_historical_synthetic_receipts() -> None:
    july = json.loads((ROOT / "docs/evidence/2026-07-14-sound-s14-dual-class-benchmark.json").read_text())
    august = json.loads((ROOT / "docs/evidence/2026-08-12-sound-s14-live-rerun.json").read_text())

    assert {row["hardware_class"] for row in july["classes"]} == {"x86_linux", "apple_silicon"}
    assert [row["hardware_class"] for row in august["classes"]] == ["apple_silicon"]
    assert august["second_class_status"] == "external_host_unavailable"
    assert july["clip_count"] == august["clip_count"] == DEFAULT_CLIP_COUNT == 64
    assert FixtureSpec().clip_duration_seconds == pytest.approx(0.15)
    assert DEFAULT_CLIP_COUNT * FixtureSpec().clip_duration_seconds == pytest.approx(9.6)

    active_status = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").lower()
        for path in ("README.md", "docs/status/PHASE_CHECKPOINTS.md", "docs/status/DEFERRED.md")
    )
    assert "thin s12" in active_status
    assert "synthetic" in active_status
    assert "not a full episode" in active_status
    assert "not human listening" in active_status
    assert "s13 (host joins / bindings): blocked" not in active_status
    assert "product full-episode claim: allowed" not in active_status


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("max_spend_usd", True, "bad_spend_cap"),
        ("max_spend_usd", -1, "bad_spend_cap"),
        ("max_spend_usd", float("nan"), "bad_spend_cap"),
        ("max_spend_usd", float("inf"), "bad_spend_cap"),
        ("max_spend_usd", "not-money", "bad_spend_cap"),
        ("max_spend_usd", 10**1_000, "bad_spend_cap"),
        ("estimated_spend_usd", False, "bad_spend_estimate"),
        ("estimated_spend_usd", -1, "bad_spend_estimate"),
        ("estimated_spend_usd", "not-money", "bad_spend_estimate"),
        ("estimated_spend_usd", float("nan"), "bad_spend_estimate"),
        ("estimated_spend_usd", float("-inf"), "bad_spend_estimate"),
        ("estimated_spend_usd", 10**1_000, "bad_spend_estimate"),
    ],
)
def test_money_validation_is_typed_for_planner_and_assertion(field: str, value: Any, code: str) -> None:
    kwargs = {"provider": "paid", "max_spend_usd": 2.0, "estimated_spend_usd": 1.0, field: value}
    with pytest.raises(MCPVideoError) as plan_error:
        plan_generative_last_mile("shot", **kwargs)
    assert plan_error.value.code == code

    raw = {"provider": "paid", "max_spend_usd": 2.0, "estimated_spend_usd": 1.0, field: value}
    assert _error_code(raw) == code
    model_kwargs = {
        "provider": "paid",
        "model": None,
        "prompt": "shot",
        "max_spend_usd": 2.0,
        "local_only": False,
        "estimated_spend_usd": 1.0,
        "allowed": True,
        "reason": "forged",
        "executable": True,
        "paid_path": True,
        field: value,
    }
    assert _error_code(GenerativePlan(**model_kwargs)) == code


def test_cap_validation_precedes_estimate_validation() -> None:
    raw = {"provider": "paid", "max_spend_usd": True, "estimated_spend_usd": float("nan")}
    assert _error_code(raw) == "bad_spend_cap"


def test_money_validation_precedes_new_shape_validation() -> None:
    with pytest.raises(MCPVideoError) as planner_error:
        plan_generative_last_mile("shot", provider=1, max_spend_usd=True)
    assert planner_error.value.code == "bad_spend_cap"

    raw = {"provider": 1, "max_spend_usd": True, "estimated_spend_usd": 0}
    assert _error_code(raw) == "bad_spend_cap"


@pytest.mark.parametrize(
    ("provider", "cap", "estimate", "code"),
    [
        ("paid", 0.0, 0.0, "generative_not_executable"),
        ("paid", 1.0, 2.0, "generative_not_executable"),
        ("local", 0.0, 0.0, "generative_backend_unavailable"),
        ("paid", 2.0, 1.0, "generative_backend_unavailable"),
    ],
)
def test_assertion_recomputes_policy_for_models_and_dicts(
    provider: str, cap: float, estimate: float, code: str
) -> None:
    plan = plan_generative_last_mile("shot", provider=provider, max_spend_usd=cap, estimated_spend_usd=estimate)
    assert plan.executable is False
    assert _error_code(plan) == code

    forged = plan.to_dict() | {
        "allowed": True,
        "executable": True,
        "paid_path": False,
        "adapter_ready": True,
    }
    assert _error_code(forged) == code


def test_missing_dictionary_fields_use_local_zero_defaults() -> None:
    assert _error_code({"allowed": True, "executable": True}) == "generative_backend_unavailable"


def test_planning_creates_no_media_or_provider_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("provider or process I/O attempted")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    plan = plan_generative_last_mile("shot", provider="paid", max_spend_usd=2, estimated_spend_usd=1)
    assert _error_code(plan) == "generative_backend_unavailable"
    assert list(tmp_path.iterdir()) == []


def test_tts_discovery_is_candidate_metadata_without_private_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tts_dub,
        "detect_tts_backend",
        lambda: {
            "available": True,
            "primary": "candidate",
            "backends": [{"id": "candidate", "kind": "cli", "path": "/private/bin/candidate"}],
        },
    )
    plan = plan_tts_dub("captions.srt")
    assert plan["executable"] is False
    assert plan["backend"]["available"] is True
    assert "path" not in json.dumps(plan["backend"])
    assert "adapter" in plan["reason"].lower()
    assert "execution" in plan["reason"].lower()


def test_hugging_face_hf_cli_is_not_reported_as_hyperframes(monkeypatch: pytest.MonkeyPatch) -> None:
    queried: list[str] = []

    def which(name: str) -> str | None:
        queried.append(name)
        return "/usr/local/bin/hf" if name == "hf" else None

    monkeypatch.setattr(tts_dub.shutil, "which", which)
    monkeypatch.setattr(tts_dub.importlib.util, "find_spec", lambda _name: None)
    report = tts_dub.detect_tts_backend()
    assert report == {"available": False, "primary": None, "backends": []}
    assert "hf" not in queried


@pytest.mark.parametrize(
    ("call", "code"),
    [
        (lambda: plan_generative_last_mile(1), "prompt_required"),
        (lambda: plan_generative_last_mile("shot", provider=1), "invalid_provider"),
        (lambda: plan_generative_last_mile("shot", params=[1]), "invalid_params"),
        (lambda: assert_generative_executable(1), "invalid_generative_plan"),
        (lambda: plan_tts_dub(1), "caption_required"),
        (lambda: plan_tts_dub("captions.srt", target_lang=1), "invalid_target_lang"),
    ],
)
def test_exported_planners_reject_malformed_field_types(call, code: str) -> None:
    with pytest.raises(MCPVideoError) as exc_info:
        call()
    assert exc_info.value.error_type == "validation_error"
    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("tool_name", "args", "code"),
    [
        ("video_generative_plan", (1,), "prompt_required"),
        ("video_generative_plan", ("shot", 1), "invalid_provider"),
        ("video_dub_plan", (1,), "caption_required"),
        ("video_dub_plan", ("captions.srt", 1), "invalid_target_lang"),
    ],
)
def test_mcp_planners_preserve_typed_validation_errors(tool_name: str, args: tuple[Any, ...], code: str) -> None:
    from kinocut import server_tools_intent

    result = getattr(server_tools_intent, tool_name)(*args)
    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    assert result["error"]["code"] == code


def test_mcp_plans_expose_non_executable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_dub, "detect_tts_backend", lambda: {"available": True, "primary": "piper", "backends": []})
    from kinocut.server_tools_intent import video_dub_plan, video_generative_plan

    generated = video_generative_plan("shot", provider="paid", max_spend_usd=2, estimated_spend_usd=1)
    dubbed = video_dub_plan("captions.srt")
    assert generated["success"] is True and generated["executable"] is False
    assert dubbed["success"] is True and dubbed["executable"] is False


@pytest.mark.parametrize(
    ("allow_paid_gen", "code"),
    [(False, "paid_gen_disabled"), (True, "paid_edit_backend_unavailable")],
)
def test_image_edit_mcp_preserves_nested_paid_error(tmp_path: Path, allow_paid_gen: bool, code: str) -> None:
    from kinocut.server_tools_image import image_edit

    source = tmp_path / "source.png"
    reference = tmp_path / "reference.png"
    source.write_bytes(b"not-decoded")
    reference.write_bytes(b"not-decoded")
    result = image_edit(
        str(source),
        str(reference),
        "match",
        str(tmp_path / "out"),
        prefer="gen",
        allow_paid_gen=allow_paid_gen,
    )
    assert result["success"] is False
    assert result["error"]["code"] == code


def test_active_paid_surface_descriptions_do_not_claim_configuration_is_execution() -> None:
    from kinocut.server_tools_image import image_edit as image_edit_tool
    from kinocut.server_tools_intent import video_dub_plan, video_generative_plan
    from kinocut.still_plates import edit as still_edit

    active = "\n".join(
        [
            inspect.getdoc(generative) or "",
            inspect.getdoc(generative.plan_generative_last_mile) or "",
            inspect.getdoc(generative.assert_generative_executable) or "",
            inspect.getdoc(tts_dub.detect_tts_backend) or "",
            inspect.getdoc(tts_dub.plan_tts_dub) or "",
            inspect.getdoc(image_edit_tool) or "",
            inspect.getdoc(still_edit.image_edit) or "",
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs/STILL_PLATES.md").read_text(encoding="utf-8"),
        ]
    ).lower()
    assert "no generation adapter exists" in active
    assert "no synthesis adapter exists" in active
    assert "no generation adapter" in (inspect.getdoc(video_generative_plan) or "").lower()
    assert "no synthesis adapter" in (inspect.getdoc(video_dub_plan) or "").lower()
    assert "until backend configured" not in active
    assert "until configured" not in active
    assert "no paid still-generation adapter exists" in active


def test_paid_still_error_points_to_the_available_free_path() -> None:
    from kinocut.still_plates.edit import _validate_edit_policy

    with pytest.raises(MCPVideoError) as exc_info:
        _validate_edit_policy(prefer="gen", allow_paid_gen=True, intent="match")
    assert exc_info.value.code == "paid_edit_backend_unavailable"
    suggestion = exc_info.value.suggested_action
    assert suggestion is not None
    description = suggestion["description"].lower()
    assert "prefer=edit" in description
    assert "no paid still-generation adapter exists" in description
    assert "configur" not in description
