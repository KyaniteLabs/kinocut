"""TE QoL + proposed mutations tests."""

from __future__ import annotations

from pathlib import Path

from kinocut.te import BrandKit, estimate_operation, init_project, load_cutfile, save_brand_kit, validate_cutfile
from kinocut.watching import MetricFinding, propose_mutations_from_findings


def test_init_project_scaffold(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    r = init_project(str(root), name="demo")
    assert Path(r["media_dir"]).is_dir()
    assert Path(r["cutfile"]).is_file()


def test_brand_kit_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "brand.json"
    save_brand_kit(str(path), BrandKit(name="acme", primary_color="#112233"))
    from kinocut.te import load_brand_kit

    kit = load_brand_kit(str(path))
    assert kit.name == "acme"
    assert kit.primary_color == "#112233"


def test_estimate_operation() -> None:
    est = estimate_operation("repurpose", duration_seconds=60.0)
    assert est["dry_run"] is True
    assert est["estimated_wall_seconds"] > 0
    assert est["currency"] is None


def test_cutfile_validate() -> None:
    cf = validate_cutfile({"name": "demo", "version": 1, "sources": [], "ops": [{"op": "trim", "start": 0}]})
    assert cf.name == "demo"
    assert len(cf.ops) == 1


def test_cutfile_yaml_scaffold(tmp_path: Path) -> None:
    p = tmp_path / "cutfile.yaml"
    p.write_text('name: "demo"\nversion: 1\nsources: []\nops: []\n', encoding="utf-8")
    cf = load_cutfile(str(p))
    assert cf.name == "demo"


def test_propose_mutations_from_findings() -> None:
    findings = [
        MetricFinding("duration.min", "fail", "too short", (0.0, 0.1)),
        MetricFinding("black_frames.ratio", "warn", "blackish", (0.0, 1.0)),
        MetricFinding("ok", "info", "fine"),
    ]
    props = propose_mutations_from_findings(findings)
    assert len(props) == 2
    assert all(p.apply_policy == "human_review_required" for p in props)
