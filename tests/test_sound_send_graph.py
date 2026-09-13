"""Independent pre/post-fader and ordered-saturation bus graph oracles."""

from array import array

import pytest

from kinocut_sound.routing import Bus, SendReturn


def buses(gains=(0, 0, 0)):
    return tuple(
        Bus(bus_id=name, kind=name, gain_db=gain)
        for name, gain in zip(("dialogue", "ambience", "sfx"), gains, strict=True)
    )


def send(name, source, target, gain=0, post=True):
    return SendReturn(send_id=name, source_bus_id=source, destination_bus_id=target, gain_db=gain, post_fader=post)


@pytest.mark.parametrize("post,expected", [(False, 8000), (True, 4000)])
def test_pre_and_post_fader_reads_complete_source_before_destination_gain(post, expected):
    from kinocut_sound.mix.bus_sends import BusSendGraph

    graph = BusSendGraph(
        buses((-6.020599913279624, 6.020599913279624, 0)),
        (send("a", "dialogue", "ambience", -6.020599913279624, post),),
        1,
        1,
    )
    canvases = {"dialogue": array("h", [8000]), "ambience": array("h", [0]), "sfx": array("h", [0])}
    assert graph.process_buses(canvases) is canvases
    assert canvases["dialogue"][0] == 4000 and canvases["ambience"][0] == expected


@pytest.mark.parametrize("post,expected", [(False, 9000), (True, 18000)])
def test_transitive_source_snapshot_contains_earlier_returns(post, expected):
    from kinocut_sound.mix.bus_sends import BusSendGraph

    graph = BusSendGraph(
        buses((0, 6.020599913279624, 0)),
        (send("later", "ambience", "sfx", post=post), send("first", "dialogue", "ambience")),
        1,
        1,
    )
    canvases = {"dialogue": array("h", [8000]), "ambience": array("h", [1000]), "sfx": array("h", [0])}
    graph.process_buses(canvases)
    assert canvases["ambience"][0] == 18000 and canvases["sfx"][0] == expected


def test_incoming_send_order_preserves_observable_saturation():
    from kinocut_sound.mix.bus_sends import BusSendGraph

    edges = (send("positive", "dialogue", "sfx"), send("negative", "ambience", "sfx"))
    results = []
    for order in (edges, tuple(reversed(edges))):
        canvases = {"dialogue": array("h", [30000]), "ambience": array("h", [-30000]), "sfx": array("h", [10000])}
        BusSendGraph(buses(), order, 1, 1).process_buses(canvases)
        results.append(canvases["sfx"][0])
    assert results == [2767, 10000]


@pytest.mark.parametrize("post,expected", [(False, 15000), (True, 16384)])
def test_gain_stages_do_not_fuse_across_clipping(post, expected):
    from kinocut_sound.mix.bus_sends import BusSendGraph

    graph = BusSendGraph(buses((12, 0, 0)), (send("a", "dialogue", "ambience", -6.020599913279624, post),), 1, 1)
    canvases = {"dialogue": array("h", [30000]), "ambience": array("h", [0]), "sfx": array("h", [0])}
    graph.process_buses(canvases)
    assert canvases["dialogue"][0] == 32767 and canvases["ambience"][0] == expected


@pytest.mark.parametrize("kind", ["cycle2", "cycle3", "duplicate", "unknown"])
def test_invalid_graphs_fail_before_processing(kind):
    from kinocut_sound.mix.bus_sends import BusSendGraph
    from kinocut_sound.mix._errors import MixError

    edges = [send("a", "dialogue", "ambience")]
    if kind == "cycle2":
        edges.append(send("b", "ambience", "dialogue"))
    elif kind == "cycle3":
        edges.extend((send("b", "ambience", "sfx"), send("c", "sfx", "dialogue")))
    elif kind == "duplicate":
        edges.append(send("a", "dialogue", "sfx"))
    else:
        edges.append(send("b", "missing", "sfx"))
    with pytest.raises(MixError):
        BusSendGraph(buses(), tuple(edges), 1, 1)


def test_parallel_pre_fader_edges_share_one_readonly_snapshot(monkeypatch):
    from kinocut_sound.mix import bus_sends

    edges = tuple(send(f"wire-{i}", "dialogue", "ambience", post=False) for i in range(64))
    graph = bus_sends.BusSendGraph(buses((6.020599913279624, 0, 0)), edges, 1, 1)
    observed = []
    original = bus_sends._overlay_scaled

    def inspect(target, source, factor):
        observed.append(id(source.obj))
        assert source.readonly and source[0] == 100
        with pytest.raises(TypeError):
            source[0] = 2
        original(target, source, factor)

    monkeypatch.setattr(bus_sends, "_overlay_scaled", inspect)
    canvases = {"dialogue": array("h", [100]), "ambience": array("h", [0]), "sfx": array("h", [0])}
    graph.process_buses(canvases)
    assert len(set(observed)) == 1 and len(observed) == 64
    assert canvases["ambience"][0] == 6400 and canvases["dialogue"][0] == 200
    assert graph.snapshot_bytes == 2 and graph.work_units == 199


def test_stereo_send_uses_linked_gain():
    from kinocut_sound.mix.bus_sends import BusSendGraph

    graph = BusSendGraph(buses(), (send("a", "dialogue", "ambience", -6.020599913279624),), 2, 2)
    canvases = {
        "dialogue": array("h", [8000, -4000, -6000, 3000]),
        "ambience": array("h", [0] * 4),
        "sfx": array("h", [0] * 4),
    }
    graph.process_buses(canvases)
    assert list(canvases["ambience"]) == [4000, -2000, -3000, 1500]


@pytest.mark.parametrize("kind", ["alias", "shape", "type", "missing"])
def test_invalid_canvases_rejected_without_mutation(kind):
    from kinocut_sound.mix.bus_sends import BusSendGraph
    from kinocut_sound.mix._errors import MixError

    graph = BusSendGraph(buses(), (send("a", "dialogue", "ambience"),), 1, 1)
    canvases = {"dialogue": array("h", [100]), "ambience": array("h", [0]), "sfx": array("h", [0])}
    if kind == "alias":
        canvases["ambience"] = canvases["dialogue"]
    elif kind == "shape":
        canvases["sfx"] = array("h", [0, 0])
    elif kind == "type":
        canvases["sfx"] = [0]
    else:
        del canvases["sfx"]
    with pytest.raises(MixError):
        graph.process_buses(canvases)
    assert canvases["dialogue"][0] == 100
