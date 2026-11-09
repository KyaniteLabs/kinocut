"""sound-plan-validate names the failing field and never echoes input values (#676)."""

import pytest

from kinocut_sound._errors import SoundContractError, SoundPlanValidationError
from kinocut_sound.public.adapters import _minimal_plan, invoke_sound_operation


def _validate(plan):
    return invoke_sound_operation("sound-plan-validate", plan=plan)


def test_unknown_field_reports_loc_and_type():
    with pytest.raises(SoundPlanValidationError) as exc:
        _validate({"cues": []})
    err = exc.value
    assert err.error_type == "validation_error"
    assert err.code == "invalid_plan"
    assert {"loc": ["cues"], "msg": "Extra inputs are not permitted", "type": "extra_forbidden"} in err.details
    assert "project_id: Field required" in str(err)
    assert "more)" in str(err)
    assert err.to_dict()["details"] == err.details


def test_wrong_typed_field_reports_nested_loc_without_input_value():
    plan = _minimal_plan().model_dump(mode="json")
    private_value = "/home/someone/private/prompt.txt"
    plan["episode_id"] = {"path": private_value}
    with pytest.raises(SoundPlanValidationError) as exc:
        _validate(plan)
    assert any(d["loc"] == ["episode_id"] for d in exc.value.details)
    assert private_value not in str(exc.value)
    assert private_value not in repr(exc.value.details)
    assert all(set(d) == {"loc", "msg", "type"} for d in exc.value.details)


def test_error_stays_compatible_with_value_error_and_contract_error():
    with pytest.raises(ValueError):
        _validate({})
    with pytest.raises(SoundContractError):
        _validate({})
