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

    assert len(ids) == 26
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
        "brand-render",
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

    assert summary["required_path_count"] == 26
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


class _FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def wait_for(self, **kwargs):
        self.page.waits.append((self.selector, kwargs))
        if self.page.error is not None:
            raise self.page.error


class _FakePage:
    def __init__(self, error=None):
        self.error, self.waits = error, []

    def locator(self, selector):
        return _FakeLocator(self, selector)


def test_hyperframes_probe_waits_for_enabled_play_button():
    runner = load_runner()
    page = _FakePage()
    runner.wait_for_playable(page, timeout_ms=1234, page_errors=[], failed_requests=[])
    assert page.waits == [('button[aria-label="Play"]:not([disabled])', {"state": "visible", "timeout": 1234})]


def test_hyperframes_probe_names_never_playable_with_diagnostics():
    runner = load_runner()
    timeout = type("TimeoutError", (Exception,), {})("Timeout 1234ms exceeded")
    page = _FakePage(error=timeout)
    with pytest.raises(RuntimeError, match="preview never became playable") as exc:
        runner.wait_for_playable(
            page, timeout_ms=1234, page_errors=["GSAP could not load"], failed_requests=["https://cdn.example/x.js"]
        )
    assert "GSAP could not load" in str(exc.value)
    assert "https://cdn.example/x.js" in str(exc.value)


def test_hyperframes_probe_does_not_mask_non_timeout_errors():
    runner = load_runner()
    page = _FakePage(error=ValueError("target closed"))
    with pytest.raises(ValueError, match="target closed"):
        runner.wait_for_playable(page, timeout_ms=10, page_errors=[], failed_requests=[])


def _brand_runner(runner, tmp_path, monkeypatch, gate_root):
    product = tmp_path / "product"
    (product / "assets").mkdir(parents=True)
    (product / "assets" / "kinocut-wordmark.svg").write_text("<svg/>", encoding="utf-8")
    work = tmp_path / "work"
    (work / "artifacts").mkdir(parents=True)
    monkeypatch.setenv(runner.FLEET_ROOT_ENV, str(gate_root))
    instance = object.__new__(runner.OperatorRunner)
    instance.product_root = product
    instance.product_problem = None
    instance.product_sha = "0" * 40
    instance.work = work
    instance.venv = work / "venv"
    instance.python = instance.venv / "bin" / "python"
    instance.kino = instance.venv / "bin" / "kino"
    instance.hyperframes_executable = None
    instance.results = []
    instance.catalog = runner.load_catalog(CATALOG_PATH)
    instance.catalog_path = CATALOG_PATH
    return instance


def _write_fake_gate(gate_root, body):
    gate = gate_root / "ops" / "qa-brand-render" / "render_gate.py"
    gate.parent.mkdir(parents=True)
    gate.write_text(body, encoding="utf-8")
    return gate


_FAKE_GATE = """import json
import sys
from pathlib import Path

args = sys.argv[1:]
asset = args[0]
report = Path(args[args.index("--json") + 1])
report.parent.mkdir(parents=True, exist_ok=True)
result = {RESULT}
report.write_text(json.dumps({{"results": [result]}}), encoding="utf-8")
print(("PASS" if result["ok"] else "FAIL"), asset)
sys.exit(0 if result["ok"] else 1)
"""


def test_brand_render_catalog_entry_binds_the_runner_argv():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    entry = next(path for path in catalog["paths"] if path["id"] == "brand-render")

    assert entry["required"] is True
    assert entry["action"] == "brand_render"
    expanded = runner.expand_argv(
        entry["argv"],
        {
            "python": "/usr/bin/python3",
            "fleet_root": Path("/opt/fleet"),
            "product_root": Path("/src/kinocut"),
            "qa_work": Path("/qa"),
        },
    )
    assert expanded[0] == "/usr/bin/python3"
    assert expanded[1] == "/opt/fleet/ops/qa-brand-render/render_gate.py"
    assert expanded[2] == "/src/kinocut/assets/kinocut-wordmark.svg"
    assert expanded[expanded.index("--json") + 1] == "/qa/artifacts/brand-render.json"
    assert entry["command"].startswith("{{python}} {{fleet_root}}/ops/qa-brand-render/render_gate.py")


def test_brand_render_drift_is_detected_when_the_entry_stops_being_required():
    runner = load_runner()
    catalog = runner.load_catalog(CATALOG_PATH)
    entry = next(path for path in catalog["paths"] if path["id"] == "brand-render")
    entry["required"] = False

    with pytest.raises(runner.CatalogError, match="required path set drift"):
        runner.validate_catalog(catalog)


def test_brand_render_handler_passes_positive_ink_inside_the_canvas(tmp_path, monkeypatch):
    runner = load_runner()
    instance = _brand_runner(runner, tmp_path, monkeypatch, tmp_path / "fleet")
    _write_fake_gate(
        tmp_path / "fleet",
        _FAKE_GATE.format(
            RESULT=(
                '{"path": asset, "ok": True, "ink_pixels": 1234, '
                '"ink_bbox": [10.0, 10.0, 90.0, 40.0], "canvas": [0.0, 0.0, 100.0, 50.0], '
                '"outside_edges": []}'
            )
        ),
    )

    instance._run_brand_render(instance._entry("brand-render"))

    assert instance.results[-1]["status"] == "PASS"
    assert "ink_pixels=1234" in instance.results[-1]["detail"]
    assert "ink_bbox=[10.000, 10.000, 90.000, 40.000]" in instance.results[-1]["detail"]


def test_brand_render_handler_fails_a_blanked_asset(tmp_path, monkeypatch):
    runner = load_runner()
    instance = _brand_runner(runner, tmp_path, monkeypatch, tmp_path / "fleet")
    _write_fake_gate(
        tmp_path / "fleet",
        _FAKE_GATE.format(
            RESULT=(
                '{"path": asset, "ok": False, "ink_pixels": 0, '
                '"ink_bbox": [10.0, 60.0, 90.0, 90.0], "canvas": [0.0, 0.0, 100.0, 50.0], '
                '"outside_edges": ["bottom"], "reason": "0 ink pixels"}'
            )
        ),
    )

    instance._run_brand_render(instance._entry("brand-render"))

    assert instance.results[-1]["status"] == "FAIL"
    assert "ink_pixels=0" in instance.results[-1]["detail"]
    assert "outside_edges" in instance.results[-1]["detail"]


def test_brand_render_handler_blocks_when_the_gate_cannot_run(tmp_path, monkeypatch):
    runner = load_runner()
    instance = _brand_runner(runner, tmp_path, monkeypatch, tmp_path / "fleet")
    _write_fake_gate(tmp_path / "fleet", "import sys\nprint('ERROR no chrome', file=sys.stderr)\nsys.exit(2)\n")

    instance._run_brand_render(instance._entry("brand-render"))

    assert instance.results[-1]["status"] == "BLOCKED"
    assert "could not run" in instance.results[-1]["detail"]
