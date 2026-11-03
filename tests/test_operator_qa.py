from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "qa" / "runner.py"
CATALOG_PATH = ROOT / "qa" / "operator-paths.yaml"


def load_runner():
    spec = importlib.util.spec_from_file_location("kinocut_operator_qa_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_keeps_original_required_operator_ids_and_provenance():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    required = runner.required_paths(catalog)
    ids = [path["id"] for path in required]

    assert len(ids) == 25
    assert len(ids) == len(set(ids))
    assert {
        "clean-environment",
        "install-source",
        "install-doctor",
        "tiny-synthetic-media",
        "golden-path",
        "info",
        "trim",
        "resize",
        "subtitles",
        "waveform",
        "image-colors",
        "workflow-validate",
        "workflow-plan",
        "workflow-render",
        "workflow-inspect",
        "review-metrics",
        "sound-validation",
        "overwrite-guard",
        "source-alias-guard",
        "mcp-video_doctor",
        "mcp-video_info",
        "mcp-search_tools",
        "mcp-protocol",
        "static-review-ui",
        "hyperframes-preview",
    } <= set(ids)
    assert all(path.get("sources") for path in required)
    assert catalog["complete_e2e_catalog"] is False


def test_real_failures_and_blocked_paths_force_nonzero_and_stay_visible():
    runner = load_runner()
    results = [
        {"id": "ok", "status": "PASS", "detail": "observed"},
        {"id": "broken", "status": "FAIL", "detail": "exit 1"},
        {"id": "needs-fixture", "status": "BLOCKED", "detail": "missing fixture"},
    ]

    assert runner.exit_code(results) == 1
    rendered = "\n".join(runner.format_result(result) for result in results)
    assert "FAIL broken" in rendered
    assert "BLOCKED needs-fixture" in rendered


def test_pass_requires_every_required_path_and_success_is_zero():
    runner = load_runner()
    assert runner.exit_code([{"id": "a", "status": "PASS"}]) == 0
    assert runner.exit_code([{"id": "a", "status": "SKIP"}]) == 1


def test_catalog_command_expansion_is_argv_only_not_shell_evaluation(tmp_path):
    runner = load_runner()
    payload = "$(touch SHOULD_NOT_EXIST); *"

    expanded = runner.expand_argv(["kino", "--arg", "{{qa_work}}/input.mp4", payload], {"qa_work": tmp_path})

    assert expanded == ["kino", "--arg", f"{tmp_path}/input.mp4", payload]
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_catalog_command_executable_must_be_allowlisted():
    runner = load_runner()
    with pytest.raises(runner.CatalogError, match="not allowlisted"):
        runner.expand_argv(["/tmp/not-a-catalog-command", "--help"], {})


def test_catalog_loader_rejects_duplicate_mapping_keys(tmp_path):
    runner = load_runner()
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: 2" + chr(10) + "schema_version: 3" + chr(10), encoding="utf-8")

    with pytest.raises(runner.CatalogError, match="duplicate YAML key"):
        runner.load_catalog(duplicate)


def test_mcp_inventory_is_reported_separately_from_action_coverage():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    summary = runner.coverage_counts(
        [
            {"id": "mcp-protocol", "status": "PASS"},
            {"id": "trim", "status": "PASS"},
            {"id": "workflow-render", "status": "BLOCKED"},
        ],
        catalog,
    )

    assert summary["required_path_count"] == 25
    assert summary["reported_path_count"] == 3
    assert summary["required_operator_action_path_count"] == 20
    assert summary["passed_operator_action_path_count"] == 1
    assert summary["discovery_passed_path_ids"] == ["mcp-protocol"]


def test_catalog_validation_rejects_duplicate_path_ids():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    duplicate = dict(catalog["paths"][0])
    catalog["paths"].append(duplicate)

    with pytest.raises(runner.CatalogError, match="duplicate"):
        runner.validate_catalog(catalog)


def test_argparse_inventory_handles_wrapped_descriptions():
    runner = load_runner()
    help_text = "positional arguments:\n  {info,extract-frame}\n    info  Show info\n    extract-frame\n          Extract a frame\n\noptions:\n  -h  help\n"
    assert runner.cli_names(help_text) == ["info", "extract-frame"]


def test_waveform_uses_peaks_and_rejects_silence_and_synthetic():
    runner = load_runner()
    valid = {"success": True, "synthetic": False, "peaks": [{"time": i, "level": -21.0} for i in range(8)]}
    assert runner.measured_waveform(valid)
    assert not runner.measured_waveform({**valid, "synthetic": True})
    assert not runner.measured_waveform({**valid, "peaks": [{"time": i, "level": -120} for i in range(8)]})


def test_incomplete_catalog_cannot_hide_coverage_gaps():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    catalog["coverage_gaps"] = []
    with pytest.raises(runner.CatalogError, match="coverage"):
        runner.validate_catalog(catalog)


def test_search_tool_results_include_required_parameters():
    runner = load_runner()
    assert runner.subtitle_search_matches(
        {"success": True, "tools": [{"name": "video_subtitles", "required_params": ["input_path"]}]}
    ) == ["video_subtitles"]
    assert runner.subtitle_search_matches({"success": True, "tools": [{"name": "video_subtitles"}]}) == []


def test_empty_gap_list_requires_an_exhaustive_live_inventory_mapping():
    runner = load_runner()
    paths = [
        {"id": "trim", "category": "operator", "required": True, "argv": ["kino", "trim"]},
        {"id": "doctor", "category": "operator", "required": True, "request": {"tool": "video_doctor"}},
    ]
    catalog = {
        "setup": [],
        "paths": paths,
        "coverage_inventory": {"cli": {"trim": "trim"}, "mcp": {"video_doctor": "doctor"}},
    }
    assert runner.exhaustive_coverage(catalog, {"trim"}, {"video_doctor"})
    assert not runner.exhaustive_coverage(catalog, {"trim", "resize"}, {"video_doctor"})
    assert not runner.exhaustive_coverage(catalog, {"trim"}, {"video_doctor", "video_info"})


def test_empty_sound_plan_rejection_accepts_structured_stderr_and_retains_error():
    runner = load_runner()
    cp = subprocess.CompletedProcess(
        ["kino"],
        1,
        stdout="",
        stderr='{"success":false,"error":{"type":"unknown","message":"sound plan validation failed"}}',
    )
    error = runner.sound_plan_rejection(cp)
    assert error == {"type": "unknown", "message": "sound plan validation failed"}
    assert runner.sound_plan_rejection(subprocess.CompletedProcess(["kino"], 0, stdout=cp.stderr, stderr="")) is None


def test_browser_temporary_directory_is_short_owned_and_restores_environment(monkeypatch, tmp_path):
    runner = load_runner()
    monkeypatch.setenv("TMPDIR", str(tmp_path / ("long" * 40)))
    previous = runner.os.environ["TMPDIR"]
    with runner.browser_tempdir() as browser_tmp:
        assert len(browser_tmp) < 60
        assert Path(browser_tmp).is_dir()
        assert runner.os.environ["TMPDIR"] == browser_tmp
    assert runner.os.environ["TMPDIR"] == previous
    assert not Path(browser_tmp).exists()


def test_hyperframes_fixture_has_real_paused_animation():
    html = (ROOT / "qa" / "fixtures" / "hyperframes.html").read_text(encoding="utf-8")
    assert 'data-composition-id="kinocut-preview-proof"' in html
    assert "gsap.timeline({ paused: true })" in html
    assert 'window.__timelines["kinocut-preview-proof"] = timeline' in html
