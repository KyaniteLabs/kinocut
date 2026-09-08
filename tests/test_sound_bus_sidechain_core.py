"""Fixed detector snapshots make bus-control cycles non-iterative."""

from array import array
import pytest

from kinocut_sound.routing import DuckingSidechain
from kinocut_sound.mix.bus_sidechains import BusSidechains
from kinocut_sound.mix._errors import MixError


def policy(source, target, attenuation=6.020599913279624):
    return DuckingSidechain(
        source_bus_id=source, target_bus_id=target, attenuation_db=attenuation, attack_ms=1, release_ms=1, recovery_ms=1
    )


def test_two_way_control_uses_fixed_original_detectors():
    processor = BusSidechains((policy("a", "b", 24), policy("b", "a")), ("a", "b"), 1, 1, 1000)
    canvases = {"a": array("h", [10000]), "b": array("h", [1000])}
    processor.process_buses(canvases)
    assert canvases["b"][0] == 63  # Now below threshold, but b's snapshot still contains1000.
    assert canvases["a"][0] == 5000
    assert [row["summary"]["active_frames"] for row in processor.measurements] == [1, 1]


def test_same_target_controllers_compound_in_declared_order():
    import math

    half = policy("a", "c")
    sixty = policy("b", "c", -20 * math.log10(0.6))
    outcomes = []
    for policies in ((half, sixty), (sixty, half)):
        canvases = {"a": array("h", [10000]), "b": array("h", [10000]), "c": array("h", [5])}
        BusSidechains(policies, tuple(canvases), 1, 1, 1000).process_buses(canvases)
        outcomes.append(canvases["c"][0])
    assert outcomes == [1, 2]


def test_one_readonly_snapshot_per_source(monkeypatch):
    from kinocut_sound.mix import bus_sidechains

    processor = BusSidechains((policy("a", "b"), policy("a", "c")), ("a", "b", "c"), 2, 1, 1000)
    original = bus_sidechains.duck_pcm_in_place
    seen = []

    def inspect(samples, detector, *args):
        assert detector.readonly
        seen.append(id(detector.obj))
        with pytest.raises(TypeError):
            detector[0] = 1
        return original(samples, detector, *args)

    monkeypatch.setattr(bus_sidechains, "duck_pcm_in_place", inspect)
    canvases = {"a": array("h", [10000, 0]), "b": array("h", [8000, 8000]), "c": array("h", [-6000, -6000])}
    processor.process_buses(canvases)
    assert len(set(seen)) == 1 and len(seen) == 2
    assert list(canvases["b"]) == [4000, 8000] and list(canvases["c"]) == [-3000, -6000]
    assert processor.snapshot_bytes == 4 and processor.work_units == 13


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "zero", "alias", "shape"])
def test_invalid_controller_graph_or_buffers_fail(kind):
    policies = (policy("a", "b"),)
    if kind == "duplicate":
        policies *= 2
    elif kind == "unknown":
        policies = (policy("missing", "b"),)
    canvases = {"a": array("h", [1000]), "b": array("h", [1000])}
    if kind == "alias":
        canvases["b"] = canvases["a"]
    elif kind == "shape":
        canvases["b"] = array("h", [0, 0])
    with pytest.raises(MixError):
        BusSidechains(policies, ("a", "b"), 0 if kind == "zero" else 1, 1, 1000).process_buses(canvases)


def test_outer_stage_rejects_aliases_before_inner_faders_mutate_them():
    from kinocut_sound.routing import Routing, Bus
    from kinocut_sound.mix.static_routing import StaticRouting
    from kinocut_sound.mix.sidechain_routing import SidechainRouting

    declared = Routing(
        buses=(Bus(bus_id="a", kind="dialogue", gain_db=6.020599913279624), Bus(bus_id="b", kind="ambience")),
        sidechains=(policy("a", "b"),),
    )
    inner = StaticRouting(declared.model_copy(update={"sidechains": ()}), (), 1, ("a", "b"), ())
    outer = SidechainRouting(declared, inner, 1, 1, 1000)
    shared = array("h", [10000])
    with pytest.raises(MixError):
        outer.process_buses({"a": shared, "b": shared})
    assert shared[0] == 10000
