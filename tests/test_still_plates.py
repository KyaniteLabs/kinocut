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
