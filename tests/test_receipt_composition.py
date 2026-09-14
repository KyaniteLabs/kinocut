"""Tests for the Video Receipt ``composition_source`` provenance field (K4).

``composition_source`` is schema-required (`live-html` | `capture`). A
``capture`` composition must produce a visible warning-class finding without
blocking; a missing or unknown value is a schema error for every consumer
(the shared validator, the golden path, and the confidence benchmark).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from kinocut.receipts_composition import (
    COMPOSITION_SOURCE_CAPTURE,
    COMPOSITION_SOURCE_LIVE_HTML,
    composition_source_findings,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH_PATH = ROOT / "scripts" / "golden_path.py"
BENCHMARK_PATH = ROOT / "workflows" / "benchmarks" / "run_confidence_benchmark.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


golden_path = _load_module("k3k4_golden_path", GOLDEN_PATH_PATH)
benchmark = _load_module("k3k4_run_confidence_benchmark", BENCHMARK_PATH)


def _receipt(
    source: str | None = COMPOSITION_SOURCE_LIVE_HTML,
    detail: Any = "hyperframes://projects/demo",
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "run_id": "r1",
        "user_intent": "Ship a checked vertical short.",
    }
    if source is not None:
        receipt["composition_source"] = source
    if detail is not None:
        receipt["composition_source_detail"] = detail
    return receipt


class TestCompositionSourceFindings:
    def test_live_html_receipt_is_clean(self):
        assert composition_source_findings(_receipt()) == []

    def test_missing_field_is_a_schema_error(self):
        findings = composition_source_findings(_receipt(source=None, detail=None))
        assert [f["code"] for f in findings] == ["composition_source_required"]
        assert findings[0]["severity"] == "error"

    def test_unknown_value_is_a_schema_error(self):
        findings = composition_source_findings(_receipt(source="screen-studio"))
        assert [f["code"] for f in findings] == ["composition_source_invalid"]
        assert findings[0]["severity"] == "error"

    def test_capture_carries_a_warning_and_no_error(self):
        findings = composition_source_findings(_receipt(source=COMPOSITION_SOURCE_CAPTURE, detail="synthetic fixture"))
        assert [f["severity"] for f in findings] == ["warning"]
        assert findings[0]["code"] == "composition_source_capture"

    def test_blank_detail_is_a_schema_error(self):
        findings = composition_source_findings(_receipt(detail="   "))
        assert [f["code"] for f in findings] == ["composition_source_detail_invalid"]
        assert findings[0]["severity"] == "error"

    def test_non_mapping_receipt_is_a_schema_error(self):
        findings = composition_source_findings("not-a-receipt")
        assert findings[0]["severity"] == "error"


class TestGoldenPathIntegration:
    def test_validate_composition_raises_on_missing_field(self):
        with pytest.raises(golden_path.GoldenPathError, match="composition_source"):
            golden_path._validate_composition(_receipt(source=None, detail=None))

    def test_validate_composition_returns_capture_warnings_without_raising(self):
        warnings = golden_path._validate_composition(
            _receipt(source=COMPOSITION_SOURCE_CAPTURE, detail="synthetic fixture")
        )
        assert [w["code"] for w in warnings] == ["composition_source_capture"]


class TestConfidenceBenchmarkIntegration:
    def _check_names(self, receipt: dict[str, Any]) -> dict[str, dict[str, str]]:
        checks = benchmark._check_receipt(receipt)
        return {check["name"]: check for check in checks}

    def _fully_valid_receipt(self, tmp_path: Path, source: str, detail: str) -> dict[str, Any]:
        artifacts = tmp_path / "output"
        artifacts.mkdir(parents=True, exist_ok=True)
        files = {}
        for name in ("final_clip.mp4", "quality.json", "release_checkpoint.json", "thumbnail.jpg"):
            path = artifacts / name
            path.write_bytes(name.encode())
            files[name] = str(path)
        receipt = _receipt(source=source, detail=detail)
        receipt["quality"] = {"all_passed": True, "overall_score": 90.0}
        receipt["review_artifacts"] = {
            "final_video": files["final_clip.mp4"],
            "quality_report": files["quality.json"],
            "release_checkpoint": files["release_checkpoint.json"],
            "thumbnail": files["thumbnail.jpg"],
            "storyboard": ["f1.jpg", "f2.jpg", "f3.jpg", "f4.jpg"],
        }
        receipt["human_review"] = {"required": True, "status": "pending"}
        return receipt

    def test_live_html_receipt_passes_clean(self):
        check = self._check_names(_receipt())["composition_source_live_html"]
        assert check["status"] == "pass"

    def test_capture_receipt_is_visible_but_does_not_fail_the_benchmark(self, tmp_path):
        receipt = self._fully_valid_receipt(tmp_path, source=COMPOSITION_SOURCE_CAPTURE, detail="synthetic fixture")
        checks = benchmark._check_receipt(receipt)
        by_name = {check["name"]: check for check in checks}
        assert by_name["composition_source_capture"]["status"] == "warn"
        assert all(check["status"] != "fail" for check in checks)

    def test_missing_field_fails_the_composition_schema_check(self):
        check = self._check_names(_receipt(source=None, detail=None))["composition_source_schema"]
        assert check["status"] == "fail"


class TestWorkflowEmitters:
    @pytest.mark.parametrize(
        "workflow",
        ["03-explainer-video", "05-confidence-baseline", "06-repurpose-package"],
    )
    def test_receipt_emitters_declare_composition_source(self, workflow: str):
        source = (ROOT / "workflows" / workflow / "workflow.py").read_text(encoding="utf-8")
        assert '"composition_source": "capture"' in source
        assert '"composition_source_detail":' in source
