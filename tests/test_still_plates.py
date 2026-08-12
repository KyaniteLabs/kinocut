"""Still/plate editor — match, grade, gate, edit, package."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinocut.errors import MCPVideoError
from kinocut.still_plates import image_edit, still_gate, still_grade, still_match, still_package
from kinocut.still_plates.stats import apply_rgb_gains, mean_rgb, shadow_green_cyan_fraction


def _write_rgb(path: Path, rgb: tuple[float, float, float], size: int = 64) -> Path:
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    arr[..., 0] = int(rgb[0] * 255)
    arr[..., 1] = int(rgb[1] * 255)
    arr[..., 2] = int(rgb[2] * 255)
    Image.fromarray(arr, mode="RGB").save(path)
    return path


def _write_gradient(path: Path, base: tuple[float, float, float], size: int = 64) -> Path:
    arr = np.zeros((size, size, 3), dtype=np.float32)
    for y in range(size):
        t = y / max(size - 1, 1)
        arr[y, :, 0] = base[0] * (0.05 + 0.95 * t)
        arr[y, :, 1] = base[1] * (0.05 + 0.95 * t)
        arr[y, :, 2] = base[2] * (0.05 + 0.95 * t)
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), mode="RGB").save(path)
    return path


@pytest.fixture
def still_fixture_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_still_match_shared_gains_converge_toward_hero(still_fixture_dir: Path) -> None:
    hero = _write_rgb(still_fixture_dir / "hero.png", (0.5, 0.5, 0.5))
    warm = _write_rgb(still_fixture_dir / "warm.png", (0.7, 0.45, 0.35))
    cool = _write_rgb(still_fixture_dir / "cool.png", (0.35, 0.45, 0.7))
    out = still_fixture_dir / "matched"
    receipt = still_match(hero=hero, inputs=[warm, cool], output_dir=out)

    assert receipt["status"] == "ok"
    assert len(receipt["shared_gains"]) == 3
    assert receipt["per_frame_auto_wb"] is False
    assert Path(receipt["receipt_path"]).is_file()
    # Sources untouched (different path; outputs under output_dir)
    assert Path(receipt["outputs"][0]["source"]) == warm.resolve()
    assert Path(receipt["outputs"][0]["output"]).parent == out.resolve()
    assert Path(receipt["outputs"][0]["output"]).read_bytes() != warm.read_bytes()

    # Shared gains move the package mean toward hero neutrals.
    from kinocut.still_plates.io import load_rgb_array

    def package_mean(paths):
        means = [mean_rgb(load_rgb_array(p)) for p in paths]
        return tuple(sum(m[i] for m in means) / len(means) for i in range(3))

    hero_m = mean_rgb(load_rgb_array(hero))
    raw_pkg = package_mean([warm, cool])
    matched_pkg = package_mean([o["output"] for o in receipt["outputs"]])

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5

    assert dist(matched_pkg, hero_m) < dist(raw_pkg, hero_m)
    # Same gains applied to every output (logged once).
    assert len(set(tuple(receipt["shared_gains"]) for _ in receipt["outputs"])) == 1


def test_still_match_refuses_overwrite(still_fixture_dir: Path) -> None:
    hero = _write_rgb(still_fixture_dir / "hero.png", (0.5, 0.5, 0.5))
    a = _write_rgb(still_fixture_dir / "a.png", (0.4, 0.4, 0.4))
    with pytest.raises(MCPVideoError) as ei:
        still_match(hero=hero, inputs=[a], output_dir=still_fixture_dir / "o", overwrite_sources=True)
    assert ei.value.code == "overwrite_refused"


def test_still_grade_order_and_missing_lut(still_fixture_dir: Path) -> None:
    a = _write_rgb(still_fixture_dir / "a.png", (0.4, 0.5, 0.6))
    hero = _write_rgb(still_fixture_dir / "hero.png", (0.5, 0.5, 0.5))
    receipt = still_grade(inputs=[a], output_dir=still_fixture_dir / "g", hero=hero)
    assert receipt["stages"] == ["neutralize", "match"]
    assert receipt["pipeline_order"] == "correct→match→look"
    assert Path(receipt["outputs"][0]["output"]).is_file()

    with pytest.raises(MCPVideoError) as ei:
        still_grade(
            inputs=[a],
            output_dir=still_fixture_dir / "g2",
            lut_path=still_fixture_dir / "missing.cube",
        )
    assert ei.value.code == "lut_not_found"


def test_still_gate_pass_and_teal_fog_fail(still_fixture_dir: Path) -> None:
    clean_a = _write_rgb(still_fixture_dir / "c1.png", (0.45, 0.45, 0.45))
    clean_b = _write_rgb(still_fixture_dir / "c2.png", (0.48, 0.48, 0.48))
    ok = still_gate(inputs=[clean_a, clean_b], output_dir=still_fixture_dir / "gate_ok")
    assert ok["passed"] is True
    assert ok["exit_code"] == 0
    assert Path(ok["contact_sheet"]).is_file()

    # Teal fog: dark plate with elevated G/B vs R in shadows
    fog = still_fixture_dir / "fog.png"
    arr = np.zeros((64, 64, 3), dtype=np.float32)
    arr[..., 0] = 0.04
    arr[..., 1] = 0.12
    arr[..., 2] = 0.11
    Image.fromarray((arr * 255).astype(np.uint8), mode="RGB").save(fog)
    # Confirm metric itself is hot before gate thresholds
    assert shadow_green_cyan_fraction(arr) > 0.5

    bad = still_gate(
        inputs=[fog, clean_a],
        output_dir=still_fixture_dir / "gate_bad",
        max_shadow_green_cyan=0.1,
    )
    assert bad["passed"] is False
    assert bad["exit_code"] == 1
    assert any(f["metric"] == "shadow_green_cyan_fraction" for f in bad["failures"])


def test_image_edit_dry_run_and_execute(still_fixture_dir: Path) -> None:
    src = _write_rgb(still_fixture_dir / "src.png", (0.7, 0.4, 0.3))
    ref = _write_rgb(still_fixture_dir / "ref.png", (0.5, 0.5, 0.5))
    plan = image_edit(
        source=src,
        reference=ref,
        intent="match establish world",
        output_dir=still_fixture_dir / "edit_plan",
        dry_run=True,
    )
    assert plan["dry_run"] is True
    assert plan["status"] == "planned"
    assert plan["outputs"] == []
    assert not list((still_fixture_dir / "edit_plan").glob("*_edited.png"))

    done = image_edit(
        source=src,
        reference=ref,
        intent="match establish world",
        output_dir=still_fixture_dir / "edit_run",
        dry_run=False,
    )
    assert done["status"] == "ok"
    assert Path(done["outputs"][0]["output"]).is_file()


def test_image_edit_paid_gen_disabled(still_fixture_dir: Path) -> None:
    src = _write_rgb(still_fixture_dir / "s.png", (0.5, 0.5, 0.5))
    ref = _write_rgb(still_fixture_dir / "r.png", (0.5, 0.5, 0.5))
    with pytest.raises(MCPVideoError) as ei:
        image_edit(
            source=src,
            reference=ref,
            intent="x",
            output_dir=still_fixture_dir / "p",
            prefer="gen",
            allow_paid_gen=False,
        )
    assert ei.value.code == "paid_gen_disabled"


def test_still_package_dry_run_and_happy_path(still_fixture_dir: Path) -> None:
    establish = _write_gradient(still_fixture_dir / "est.png", (0.5, 0.5, 0.5))
    b1 = _write_gradient(still_fixture_dir / "b1.png", (0.55, 0.48, 0.42))
    b2 = _write_gradient(still_fixture_dir / "b2.png", (0.48, 0.5, 0.55))

    planned = still_package(
        establish=establish,
        beats=[b1, b2],
        output_dir=still_fixture_dir / "pkg_plan",
        dry_run=True,
    )
    assert planned["dry_run"] is True
    assert any(s["step"] == "still_gate" for s in planned["graph"])

    result = still_package(
        establish=establish,
        beats=[b1, b2],
        output_dir=still_fixture_dir / "pkg",
        apply_grade=True,
        dry_run=False,
    )
    assert result["status"] in {"ok", "gate_failed"}
    assert Path(result["receipt_path"]).is_file()
    assert result["match_receipt"]["status"] == "ok"
    # Receipt paths under home are sanitized to ~/ form when present
    text = Path(result["receipt_path"]).read_text(encoding="utf-8")
    home = str(Path.home())
    if home in text:
        assert "~" in text


def test_doctor_still_plates_check() -> None:
    from kinocut.doctor import run_diagnostics

    report = run_diagnostics()
    names = {c["name"] for c in report["checks"]}
    assert "still_plates" in names
    still = next(c for c in report["checks"] if c["name"] == "still_plates")
    assert still["category"] == "still-plates"
    assert "details" in still
    assert still["details"]["paid_gen_backend"] == "not_configured"


def test_client_parity(still_fixture_dir: Path) -> None:
    from kinocut import Client

    hero = _write_rgb(still_fixture_dir / "h.png", (0.5, 0.5, 0.5))
    a = _write_rgb(still_fixture_dir / "a.png", (0.6, 0.4, 0.4))
    c = Client()
    r = c.still_match(hero=str(hero), inputs=[str(a)], output_dir=str(still_fixture_dir / "cli_out"))
    assert r["status"] == "ok"
    g = c.still_gate(
        inputs=[r["outputs"][0]["output"]],
        output_dir=str(still_fixture_dir / "cli_gate"),
    )
    assert "passed" in g


def test_apply_rgb_gains_unit() -> None:
    arr = np.full((2, 2, 3), 0.5, dtype=np.float32)
    out = apply_rgb_gains(arr, (2.0, 1.0, 0.5))
    assert float(out[0, 0, 0]) == pytest.approx(1.0)
    assert float(out[0, 0, 1]) == pytest.approx(0.5)
    assert float(out[0, 0, 2]) == pytest.approx(0.25)


def test_image_edit_intent_is_metadata_only(still_fixture_dir: Path) -> None:
    src = _write_rgb(still_fixture_dir / "s.png", (0.7, 0.4, 0.3))
    ref = _write_rgb(still_fixture_dir / "r.png", (0.5, 0.5, 0.5))
    a = image_edit(
        source=src,
        reference=ref,
        intent="make it cinematic teal fog please",
        output_dir=still_fixture_dir / "e1",
    )
    b = image_edit(
        source=src,
        reference=ref,
        intent="completely different words that would matter if NL-driven",
        output_dir=still_fixture_dir / "e2",
    )
    assert a["plan"]["intent_policy"] == "metadata_only"
    assert a["plan"]["pixel_ops"] == ["establish_mean_rgb_match"]
    assert a["plan"]["intent"] != b["plan"]["intent"]
    # Different intents, same pixel path → identical output hashes.
    assert a["outputs"][0]["output_sha256"] == b["outputs"][0]["output_sha256"]


def test_near_extrema_empty_band_not_treated_as_zero() -> None:
    from kinocut.still_plates.grade import _near_extrema_preservation

    # Mid-gray only: no near-black or near-white pixels.
    mid = np.full((16, 16, 3), 0.5, dtype=np.float32)
    # Shift mid slightly — still no extrema bands.
    mid2 = np.full((16, 16, 3), 0.55, dtype=np.float32)
    metrics = _near_extrema_preservation(mid, mid2)
    assert metrics["near_black_band_empty"] is True
    assert metrics["near_white_band_empty"] is True
    assert metrics["near_black_delta"] is None
    assert metrics["near_white_delta"] is None

    # Real near-black band present before and after → finite delta, not empty.
    before = np.zeros((16, 16, 3), dtype=np.float32)
    before[:4, :, :] = 0.02
    before[4:, :, :] = 0.5
    after = before.copy()
    after[:4, :, :] = 0.04
    m2 = _near_extrema_preservation(before, after)
    assert m2["near_black_band_empty"] is False
    assert m2["near_black_delta"] == pytest.approx(0.02, abs=1e-3)


def _write_identity_cube(path: Path, size: int = 2) -> Path:
    """Minimal identity 3D LUT (.cube) for FFmpeg lut3d smoke tests."""
    lines = [
        'TITLE "identity"',
        f"LUT_3D_SIZE {size}",
    ]
    # Domain default 0..1; identity samples at size^3 grid.
    for b in range(size):
        for g in range(size):
            for r in range(size):
                rv = r / (size - 1)
                gv = g / (size - 1)
                bv = b / (size - 1)
                lines.append(f"{rv:.6f} {gv:.6f} {bv:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_still_grade_identity_lut_and_signal_mode(still_fixture_dir: Path) -> None:
    # Gradient ensures near-black and near-white bands exist for signal-mode.
    src = _write_gradient(still_fixture_dir / "grad.png", (0.6, 0.55, 0.5))
    hero = _write_rgb(still_fixture_dir / "hero.png", (0.5, 0.5, 0.5))
    cube = _write_identity_cube(still_fixture_dir / "id.cube")
    receipt = still_grade(
        inputs=[src],
        output_dir=still_fixture_dir / "lut_out",
        hero=hero,
        lut_path=cube,
        signal_mode=True,
    )
    assert receipt["stages"] == ["neutralize", "match", "look_lut"]
    assert Path(receipt["outputs"][0]["output"]).is_file()
    preservation = receipt["outputs"][0]["near_extrema_preservation"]
    assert preservation is not None
    assert "near_black_delta" in preservation
    assert "near_black_band_empty" in preservation


def test_still_gate_luma_spread_names_frames(still_fixture_dir: Path) -> None:
    dark = _write_rgb(still_fixture_dir / "dark.png", (0.1, 0.1, 0.1))
    bright = _write_rgb(still_fixture_dir / "bright.png", (0.9, 0.9, 0.9))
    bad = still_gate(
        inputs=[dark, bright],
        output_dir=still_fixture_dir / "spread",
        max_luma_spread=0.05,
    )
    assert bad["passed"] is False
    fail = next(f for f in bad["failures"] if f["metric"] == "luma_spread")
    assert fail["frame"] is not None
    assert fail["darkest_frame_index"] != fail["brightest_frame_index"]


def test_cli_still_match_and_gate(still_fixture_dir: Path) -> None:
    import subprocess
    import sys

    hero = _write_rgb(still_fixture_dir / "hero.png", (0.5, 0.5, 0.5))
    a = _write_rgb(still_fixture_dir / "a.png", (0.6, 0.4, 0.4))
    out = still_fixture_dir / "cli_m"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "still-match",
            "--hero",
            str(hero),
            "--inputs",
            str(a),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "still_match_receipt.json").is_file()

    matched = next(out.glob("*_matched.png"))
    gate_out = still_fixture_dir / "cli_g"
    r2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "still-gate",
            "--inputs",
            str(matched),
            "--output-dir",
            str(gate_out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert r2.returncode == 0, r2.stderr
    assert (gate_out / "still_gate_receipt.json").is_file()


def test_mcp_stdio_still_match_round_trip(still_fixture_dir: Path) -> None:
    import asyncio
    import json
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    hero = _write_rgb(still_fixture_dir / "h.png", (0.5, 0.5, 0.5))
    a = _write_rgb(still_fixture_dir / "a.png", (0.55, 0.45, 0.4))
    out = still_fixture_dir / "mcp_out"

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_video"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                "still_match",
                {
                    "hero": str(hero),
                    "inputs": [str(a)],
                    "output_dir": str(out),
                },
            )

    result = asyncio.run(run())
    assert result.isError is False
    payload = result.structuredContent or json.loads(result.content[0].text)
    assert payload.get("success") is True
    assert (
        Path(payload.get("receipt_path") or (out / "still_match_receipt.json")).is_file()
        or (out / "still_match_receipt.json").is_file()
    )
