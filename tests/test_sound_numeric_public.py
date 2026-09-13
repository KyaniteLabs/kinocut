"""Public numeric validation must not bypass a supplied invalid plan."""

from copy import deepcopy
import warnings

import pytest

from kinocut import Client
from kinocut_sound._errors import SoundContractError
from kinocut_sound.public.adapters import _minimal_plan, invoke_sound_operation
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.master_request import load_master_request
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.sound_numeric_cases import SHA


@pytest.mark.parametrize("value", [True, False])
def test_public_plan_rejects_boolean_duration(value):
    plan = _minimal_plan().model_dump(mode="json")
    plan["timeline"]["cues"][0]["duration_seconds"] = value
    with pytest.raises(ValueError):
        Client().sound_plan_validate(plan)


@pytest.mark.parametrize("value", [{}, False, 0, ""])
def test_explicit_invalid_plan_cannot_select_demo(value):
    with pytest.raises(ValueError):
        Client().sound_plan_validate(value)


def test_typed_plan_mutation_is_revalidated():
    plan = _minimal_plan()
    cues = plan.timeline.cues
    bad_cue = cues[0].model_copy(update={"duration_seconds": True})
    bad = plan.model_copy(update={"timeline": plan.timeline.model_copy(update={"cues": (bad_cue, *cues[1:])})})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(ValueError):
            Client().sound_plan_validate(bad)


def test_valid_typed_and_raw_plan_keep_public_hash():
    plan = _minimal_plan()
    assert Client().sound_plan_validate(plan) == Client().sound_plan_validate(plan.model_dump(mode="json"))
    assert (
        invoke_sound_operation("sound-plan-validate", plan_json=plan.model_dump(mode="json"))["plan_hash"]
        == plan.canonical_id()
    )
    assert Client().sound_plan_validate() == Client().sound_plan_validate(None)


def test_plan_aliases_are_not_silently_ignored():
    plan = _minimal_plan().model_dump(mode="json")
    with pytest.raises(ValueError):
        invoke_sound_operation("sound-plan-validate", plan=plan, plan_json=plan)
    with pytest.raises(ValueError):
        invoke_sound_operation("sound-plan-validate", unrelated=True)


def test_voice_plan_alias_is_selected_and_revalidated(monkeypatch):
    from kinocut_sound.public.adapters import SoundPythonAdapter

    plan = _minimal_plan().model_dump(mode="json")
    seen = []
    monkeypatch.setattr(SoundPythonAdapter, "voice_batch", lambda self, value: seen.append(value) or {"ok": True})
    invoke_sound_operation("sound-voice-batch", plan=None, plan_json=plan)
    assert seen == [plan]
    with pytest.raises(ValueError):
        invoke_sound_operation("sound-voice-batch", plan=plan, plan_json=plan)


def test_typed_voice_plan_cannot_bypass_numeric_validation(monkeypatch):
    from kinocut_sound.public import adapters

    plan = _minimal_plan()
    cue = plan.timeline.cues[0].model_copy(update={"duration_seconds": True})
    plan = plan.model_copy(update={"timeline": plan.timeline.model_copy(update={"cues": (cue,)})})
    monkeypatch.setattr(adapters, "BatchPlanner", lambda **kwargs: pytest.fail("invalid plan reached rendering"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(ValueError):
            adapters.SoundPythonAdapter().voice_batch(plan)


@pytest.mark.parametrize("value", [True, False])
def test_mix_request_rejects_boolean_timeline(mix_project, value):  # noqa: F811
    _, request = mix_project
    load_mix_request(request)
    changed = deepcopy(request)
    changed["plan"]["timeline"]["cues"][0]["duration_seconds"] = value
    with pytest.raises(SoundContractError):
        load_mix_request(changed)


@pytest.mark.parametrize("value", [True, False])
def test_master_request_rejects_boolean_tolerance(value):
    request = {"source": {"path": "source.wav", "sha256": SHA}, "output_path": "master.zip"}
    load_master_request(request, ".")
    request["delivery"] = {"loudness": {"integrated_lufs": -14, "true_peak_dbtp": -1, "tolerance_lu": value}}
    with pytest.raises(SoundContractError):
        load_master_request(request, ".")


@pytest.mark.parametrize("kind", ["empty", "boolean"])
def test_actual_plan_cli_and_mcp_reject_invalid_input(tmp_path, kind):
    import asyncio
    import json
    import subprocess
    import sys

    valid = _minimal_plan().model_dump(mode="json")
    invalid = {} if kind == "empty" else deepcopy(valid)
    if kind == "boolean":
        invalid["timeline"]["cues"][0]["duration_seconds"] = True
    path = tmp_path / "plan.json"
    args = [sys.executable, "-m", "kinocut", "--format", "json", "sound", "plan-validate", "--plan-json", str(path)]
    path.write_text(json.dumps(valid))
    good = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["plan_hash"] == Client().sound_plan_validate(valid)["plan_hash"]
    path.write_text(json.dumps(invalid))
    bad = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert bad.returncode != 0
    assert "sound plan validation failed" in bad.stderr
    assert not bad.stdout
    asyncio.run(asyncio.wait_for(_mcp_plans(valid, invalid), 30))


async def _mcp_plans(valid, invalid):
    import json
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        good = await session.call_tool("sound_plan_validate", {"plan": valid})
        assert not good.isError
        payload = good.structuredContent or json.loads(good.content[0].text)
        assert payload.get("result", payload)["ok"] is True
        bad = await session.call_tool("sound_plan_validate", {"plan": invalid})
        if not bad.isError:
            payload = bad.structuredContent or json.loads(bad.content[0].text)
            assert payload.get("result", payload).get("success") is False
