"""Alpha, effect-routing, and rendered-output compositor closeout tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.defaults import DEFAULT_GOLDEN_RENDER_SSIM_THRESHOLD
from kinocut.engine_composite_layers import composite_layers
from kinocut.errors import MCPVideoError


def _write_spec(tmp_path: Path, spec: dict, name: str = "layers.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(spec))
    return path


def _assets(tmp_path: Path) -> None:
    (tmp_path / "plate.png").write_bytes(b"plate")
    (tmp_path / "mask.png").write_bytes(b"mask")


def _base_spec() -> dict:
    return {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": [
            {"id": "background", "type": "solid", "color": "#204060"},
            {"id": "plate", "type": "image", "src": "plate.png", "position": {"x": 8, "y": 10}},
        ],
        "output": {"format": "mp4"},
    }


def _captured_graph(tmp_path: Path, monkeypatch, spec: dict):
    calls: list[list[str]] = []

    def fake_run(args):
        calls.append(args.copy())
        (tmp_path / "out.png").write_bytes(b"rendered")

    monkeypatch.setattr("kinocut.engine_composite_layers._run_ffmpeg", fake_run)
    result = composite_layers(str(_write_spec(tmp_path, spec)), output_path=str(tmp_path / "out.png"))
    graph = calls[0][calls[0].index("-filter_complex") + 1]
    return result, graph


def test_premultiplied_alpha_is_unpremultiplied_and_receipted(tmp_path, monkeypatch):
    _assets(tmp_path)
    spec = _base_spec()
    spec["layers"][1]["alpha_mode"] = "premultiplied"

    result, graph = _captured_graph(tmp_path, monkeypatch, spec)

    assert "format=rgba,unpremultiply=inplace=1" in graph
    assert result.layer_plan["features"]["alpha"] == {
        "working_mode": "straight",
        "input_modes_by_layer": {"background": "straight", "plate": "premultiplied"},
    }


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda spec: spec["layers"][1].update({"alpha_mode": "mystery"}), "invalid_alpha_mode"),
        (lambda spec: spec["layers"][0].update({"alpha_mode": "premultiplied"}), "invalid_alpha_mode"),
    ],
)
def test_invalid_alpha_semantics_fail_closed(tmp_path, mutator, code):
    _assets(tmp_path)
    spec = _base_spec()
    mutator(spec)

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(_write_spec(tmp_path, spec)), output_path=str(tmp_path / "out.mp4"), dry_run=True)

    assert excinfo.value.code == code


def test_noise_routes_to_named_layer_and_receipt(tmp_path, monkeypatch):
    _assets(tmp_path)
    spec = _base_spec()
    spec["passes"] = [
        {
            "effect": "effect-noise",
            "target": "layer:plate",
            "args": {"animated": False, "intensity": 0.1, "mode": "film"},
        }
    ]

    result, graph = _captured_graph(tmp_path, monkeypatch, spec)

    assert "noise=c0s=10:c0f=u" in graph
    assert result.layer_plan["features"]["effect_routes"] == spec["passes"]


def test_noise_routes_to_mask_and_mask_edge(tmp_path, monkeypatch):
    _assets(tmp_path)
    spec = _base_spec()
    spec["layers"][1]["mask"] = "mask.png"
    spec["passes"] = [
        {"effect": "effect-noise", "target": "layer:plate.mask", "args": {"intensity": 0.02}},
        {"effect": "effect-noise", "target": "layer:plate.mask.edge", "args": {"mode": "color"}},
    ]

    result, graph = _captured_graph(tmp_path, monkeypatch, spec)

    assert "edgedetect=mode=colormix" in graph
    assert "noise=c0s=2:c0f=u" in graph
    assert "noise=alls=5:allf=u" in graph
    assert "blend=all_mode=screen" in graph
    assert [route["target"] for route in result.layer_plan["features"]["effect_routes"]] == [
        "layer:plate.mask",
        "layer:plate.mask.edge",
    ]


@pytest.mark.parametrize(
    ("passes", "code"),
    [
        ([{"effect": "effect-glow", "target": "layer:plate"}], "unsupported_effect_route"),
        ([{"effect": "effect-noise", "target": "plate"}], "invalid_effect_route"),
        ([{"effect": "effect-noise", "target": "layer:missing"}], "unknown_effect_target"),
        ([{"effect": "effect-noise", "target": "layer:plate.mask"}], "missing_effect_mask"),
    ],
)
def test_unsupported_routes_fail_clearly(tmp_path, passes, code):
    _assets(tmp_path)
    spec = _base_spec()
    spec["passes"] = passes

    with pytest.raises(MCPVideoError) as excinfo:
        composite_layers(str(_write_spec(tmp_path, spec)), output_path=str(tmp_path / "out.mp4"), dry_run=True)

    assert excinfo.value.code == code


def test_effect_route_plan_is_deterministic(tmp_path):
    _assets(tmp_path)
    spec = _base_spec()
    spec["passes"] = [{"effect": "effect-noise", "target": "layer:plate", "args": {"intensity": 0.1}}]
    path = _write_spec(tmp_path, spec)

    first = composite_layers(str(path), output_path=str(tmp_path / "out.mp4"), dry_run=True).layer_plan
    second = composite_layers(str(path), output_path=str(tmp_path / "out.mp4"), dry_run=True).layer_plan

    assert first == second


def _make_media_assets(tmp_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.5:r=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(tmp_path / "bg.mp4"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    for name, color, size in (("plate.png", "red@0.7", "24x24"), ("title.png", "green@0.8", "16x12")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={size}:d=0.1",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgba",
                str(tmp_path / name),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )


def _rgb_frame(path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return result.stdout


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_layer_noise_does_not_change_background_pixels(tmp_path):
    _make_media_assets(tmp_path)
    control_spec = _golden_spec(multi_layer=False)
    effect_spec = json.loads(json.dumps(control_spec))
    effect_spec["passes"] = [
        {"effect": "effect-noise", "target": "layer:plate", "args": {"animated": False, "intensity": 0.2}}
    ]
    control = tmp_path / "control.png"
    effected = tmp_path / "effected.png"

    composite_layers(str(_write_spec(tmp_path, control_spec, "control.json")), output_path=str(control))
    composite_layers(str(_write_spec(tmp_path, effect_spec, "effect.json")), output_path=str(effected))
    before, after = _rgb_frame(control), _rgb_frame(effected)

    inside_changed = False
    for y in range(64):
        for x in range(64):
            offset = (y * 64 + x) * 3
            same = before[offset : offset + 3] == after[offset : offset + 3]
            if 8 <= x < 32 and 10 <= y < 34:
                inside_changed = inside_changed or not same
            elif x < 6 or x >= 34 or y < 8 or y >= 36:
                # yuv420p chroma conversion can move a boundary sample by one
                # pixel; the background beyond that bounded halo must be exact.
                assert same
    assert inside_changed


def _golden_spec(*, multi_layer: bool) -> dict:
    layers = [
        {"id": "background", "type": "video", "src": "bg.mp4"},
        {"id": "plate", "type": "image", "src": "plate.png", "position": {"x": 8, "y": 10}},
    ]
    if multi_layer:
        layers.extend(
            [
                {"id": "accent", "type": "solid", "color": "#602040", "width": 12, "height": 12},
                {"id": "title", "type": "image", "src": "title.png", "position": {"x": 40, "y": 44}},
            ]
        )
    return {
        "canvas": {"width": 64, "height": 64, "background": "#000000", "fps": 5, "duration": 0.5},
        "layers": layers,
        "output": {"format": "mp4"},
    }


@pytest.mark.slow
@pytest.mark.parametrize("multi_layer", [False, True], ids=["image-over-video", "video-image-solid-stack"])
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="requires ffmpeg")
def test_representative_composites_are_perceptually_stable(tmp_path, multi_layer):
    from kinocut.engine_compare_quality import compare_quality

    _make_media_assets(tmp_path)
    spec_path = _write_spec(tmp_path, _golden_spec(multi_layer=multi_layer))
    out_a = tmp_path / "run-a.mp4"
    out_b = tmp_path / "run-b.mp4"

    first = composite_layers(str(spec_path), output_path=str(out_a))
    second = composite_layers(str(spec_path), output_path=str(out_b))
    quality = compare_quality(str(out_a), str(out_b), metrics=["ssim"])

    assert first.layer_plan["spec_hash"] == second.layer_plan["spec_hash"]
    assert first.layer_plan["filtergraph_hash"] == second.layer_plan["filtergraph_hash"]
    assert quality.metrics["ssim"] >= DEFAULT_GOLDEN_RENDER_SSIM_THRESHOLD
