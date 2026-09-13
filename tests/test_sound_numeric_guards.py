"""Guard every inventoried field without tightening its accepted numeric controls."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinocut_sound._canonical import canonical_digest
from tests.sound_numeric_cases import MODEL_DATA, model_case, control_case

FIXTURES = Path(__file__).parent / "fixtures"
INVENTORY = json.loads((FIXTURES / "sound_numeric_guard_inventory.json").read_text())
BASELINE = json.loads((FIXTURES / "sound_numeric_baseline.json").read_text())
ROWS = INVENTORY["existing_guards"] + INVENTORY["added_guards"]
GUARDS = [(row["module"] + "." + row["model"], field) for row in ROWS for field in row["fields"]]
CONTROLS = [
    (row["model"], row["field"], kind, expected)
    for row in BASELINE["controls"]
    for kind, expected in row["expected"].items()
]


@pytest.mark.parametrize("name", sorted(MODEL_DATA))
def test_valid_companion_models_keep_canonical_data(name):
    cls, data = model_case(name)
    assert canonical_digest(cls.model_validate(data)) == BASELINE["model_hashes"][name]


@pytest.mark.parametrize("name,field", GUARDS)
@pytest.mark.parametrize("value", [True, False])
def test_numeric_boolean_is_rejected_at_its_field(name, field, value):
    cls, data = model_case(name)
    cls.model_validate(deepcopy(data))  # Companion fields must be independently valid.
    data[field] = (("voice", value),) if field == "profile_versions" else value
    expected_loc = (field, 0, 1) if field == "profile_versions" else (field,)
    with pytest.raises(ValidationError) as failure:
        cls.model_validate(data)
    assert any(error["loc"] == expected_loc for error in failure.value.errors())


@pytest.mark.parametrize("name,field,kind,expected", CONTROLS)
def test_field_specific_baseline_controls(name, field, kind, expected):
    cls, data = control_case(name, field, kind)
    if expected is None:
        with pytest.raises(ValidationError):
            cls.model_validate(data)
    else:
        assert canonical_digest(cls.model_validate(data)) == expected


def test_inventory_and_factories_cover_every_migration_row():
    assert INVENTORY["existing_guard_count"] == len(INVENTORY["existing_guards"]) == 31
    assert len(INVENTORY["added_guards"]) == 2
    assert {name for name, _ in GUARDS} <= MODEL_DATA.keys()
    controls = {(row["model"], row["field"]) for row in BASELINE["controls"]}
    assert set(GUARDS) <= controls
    for row in INVENTORY["excluded_already_before"]:
        assert row["current_mode"] == "before" and row["target_mode"] == "unchanged"


@pytest.mark.parametrize(
    "model,field",
    [
        ("kinocut_sound.receipt.OrderedInput", "in_point"),
        ("kinocut_sound.receipt.OrderedInput", "out_point"),
        ("kinocut_sound.receipt.OrderedInput", "probed_duration"),
        ("kinocut_sound.receipt.Transformation", "output_duration"),
    ],
)
@pytest.mark.parametrize("invalid", [True, False, "1.0"])
def test_preexisting_strict_receipt_fields_stay_strict(model, field, invalid):
    cls, data = model_case(model)
    data[field] = invalid
    with pytest.raises(ValidationError) as failure:
        cls.model_validate(data)
    assert any(error["loc"] == (field,) for error in failure.value.errors())
