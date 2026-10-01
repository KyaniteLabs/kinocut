"""Untrusted director plans cannot claim nonfinite or out-of-source geometry/time."""

from copy import deepcopy
import json

import pytest

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_RESOLUTION
from kinocut.te.sphere_director import parse_director_json
from kinocut.te.sphere_plan import decide_sphere_plan, validate_sphere_plan


def _plan():
    return {
        "artifact_kind": "360_assembly_plan",
        "schema_version": 1,
        "source": {"path": "source.mp4", "duration_seconds": 10, "sha256": "sha256:" + "0" * 64},
        "output": {"aspect": "16:9", "width": 1920, "height": 1080},
        "cameras": [{"id": "camera", "yaw": 0, "pitch": 0, "roll": 0, "fov": 90}],
        "layout": "single",
        "windows": [{"start": 0, "end": 10, "cameras": ["camera"], "layout": "single"}],
        "writer": {"kind": "model"},
        "status": "proposed",
    }


@pytest.mark.parametrize(
    "container,key",
    [
        ("source", "duration_seconds"),
        ("camera", "yaw"),
        ("camera", "pitch"),
        ("camera", "roll"),
        ("camera", "fov"),
        ("window", "start"),
        ("window", "end"),
        ("output", "width"),
        ("output", "height"),
    ],
)
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -float("inf"), 10**1000, "nonnumeric"])
def test_all_declared_numeric_fields_fail_closed_with_structured_errors(container, key, value):
    plan = _plan()
    target = (
        plan["cameras"][0]
        if container == "camera"
        else plan["windows"][0]
        if container == "window"
        else plan[container]
    )
    target[key] = value
    with pytest.raises(MCPVideoError) as error:
        validate_sphere_plan(plan)
    assert error.value.code == "invalid_sphere_plan"


@pytest.mark.parametrize("start,end", [(-0.1, 1), (0, 10.001), (9, 8), (5, 5)])
def test_windows_must_fit_positive_finite_source_duration(start, end):
    plan = _plan()
    plan["windows"][0].update(start=start, end=end)
    with pytest.raises(MCPVideoError) as error:
        decide_sphere_plan(plan, "approve")
    assert error.value.code == "invalid_sphere_plan"


@pytest.mark.parametrize("start,end", [(0, 10), (0, 0.1), (9.9, 10), (1, 2)])
def test_observed_valid_source_boundary_and_partial_windows_are_preserved(start, end):
    plan = _plan()
    plan["windows"][0].update(start=start, end=end)
    original = deepcopy(plan)
    assert validate_sphere_plan(plan) is plan
    assert plan == original
    assert decide_sphere_plan(plan, "approve")["windows"] == original["windows"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_json_nonstandard_numeric_constants_are_rejected_even_in_unused_fields(value):
    plan = _plan()
    plan["untrusted_notes"] = value
    with pytest.raises(MCPVideoError) as error:
        parse_director_json(json.dumps(plan))
    assert error.value.code == "invalid_sphere_plan"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cameras", [None]),
        ("windows", [None]),
        ("writer", "model"),
        ("cameras", [{}]),
        ("windows", [{"start": 0, "end": 10, "cameras": [{}]}]),
    ],
)
def test_invalid_container_shapes_are_structured(field, value):
    plan = _plan()
    plan[field] = value
    with pytest.raises(MCPVideoError) as error:
        validate_sphere_plan(plan)
    assert error.value.code == "invalid_sphere_plan"


@pytest.mark.parametrize("value", [0, 1.5, MAX_RESOLUTION + 1])
def test_output_dimension_limit_and_integrality(value):
    plan = _plan()
    plan["output"]["width"] = value
    with pytest.raises(MCPVideoError) as error:
        validate_sphere_plan(plan)
    assert error.value.code == "invalid_sphere_plan"


@pytest.mark.parametrize("field", ["layout", "status", "writer_kind", "aspect", "window_layout"])
def test_unhashable_enum_claims_raise_custom_errors(field):
    plan = _plan()
    if field == "writer_kind":
        plan["writer"]["kind"] = []
    elif field == "aspect":
        plan["output"]["aspect"] = []
    elif field == "window_layout":
        plan["windows"][0]["layout"] = []
    else:
        plan[field] = []
    with pytest.raises(MCPVideoError):
        validate_sphere_plan(plan)
