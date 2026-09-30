"""Source audits reject stale manifests and preserve their reporting contract."""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError


@pytest.fixture
def audit():
    path = Path(__file__).resolve().parents[1] / "scripts" / "audit-runtime-allocation.py"
    spec = importlib.util.spec_from_file_location("runtime_allocation_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stale_ml_manifest_raises_structured_validation_error(audit, tmp_path, monkeypatch):
    source = tmp_path / "module.py"
    source.write_text("def existing():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "ML_FUNCTIONS", {"module.py": {"removed_function"}})
    with pytest.raises(MCPVideoError) as failure:
        audit.python_units("module.py", set(), set())
    assert failure.value.to_dict() == {
        "type": "validation_error",
        "code": "stale_audit_manifest",
        "message": "Audit manifest stale for module.py: ['removed_function']",
    }


@pytest.mark.parametrize("baseline", [False, True])
def test_cli_preserves_allocations_inventory_and_baseline_source(audit, tmp_path, monkeypatch, capsys, baseline):
    files = {
        "kinocut/edit.py": 'def render():\n    """Agent guidance."""\n    return 99\n',
        "kinocut/ml.py": 'def infer():\n    """Ordinary docstring."""\n    return 9\n',
        "npm/launcher.js": "const value = 1;\n// excluded comment\n",
        "skills/kinocut/SKILL.md": "host guidance\n",
        "README.md": "support\n",
        "kinocut/new.py": "value = 2\n",
    }
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    tracked = [name for name in files if name != "kinocut/new.py"]
    head_source = files["kinocut/edit.py"].replace("99", "7")

    def git_output(args, **kwargs):
        assert kwargs == {"cwd": tmp_path, "text": True, "timeout": 15}
        if args == ["git", "ls-files"]:
            return "\n".join(tracked)
        if args == ["git", "ls-files", "--cached", "--others", "--exclude-standard"]:
            return "\n".join(files)
        if args == ["git", "diff", "HEAD", "--name-only"]:
            return "kinocut/edit.py\n"
        if args == ["git", "show", "HEAD:kinocut/edit.py"]:
            return head_source
        assert args == ["git", "rev-parse", "HEAD"]
        return "audit-revision\n"

    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "ML_FUNCTIONS", {"kinocut/ml.py": {"infer"}})
    monkeypatch.setattr(audit, "tool_functions", lambda: ({("kinocut/edit.py", "render")}, set()))
    monkeypatch.setattr(audit.subprocess, "check_output", git_output)
    output = tmp_path / "audit-output"
    monkeypatch.setattr(
        audit.sys, "argv", ["audit", "--output", str(output), *(["--baseline-head"] if baseline else [])]
    )
    audit.main()
    summary = json.loads((output / "allocation.json").read_text())
    total = {"deterministic": 32 if baseline else 40, "prose_llm": 21, "traditional_ml": 18}
    assert summary["totals"] == total
    assert summary["denominator"] == sum(total.values())
    assert summary["runtime_files"] == (3 if baseline else 4)
    assert summary["tracked_files_inventoried"] == len(tracked)
    assert summary["inventoried_files"] == (5 if baseline else 6)
    assert summary["registered_mcp_functions"] == 1
    assert summary["host_skill_prose_bytes_separate"] == len(files["skills/kinocut/SKILL.md"].encode())
    assert sum(summary["percent"].values()) == pytest.approx(100)
    assert summary["revision"] == "audit-revision"
    assert summary["ml_function_manifest"] == [{"path": "kinocut/ml.py", "function": "infer", "start": 1, "end": 3}]
    with (output / "repository-inventory.csv").open(newline="") as handle:
        inventory = {row["path"]: row for row in csv.DictReader(handle)}
    assert inventory["README.md"]["role"] == "support_or_data"
    assert inventory["kinocut/edit.py"]["role"] == "runtime_source"
    assert int(inventory["kinocut/edit.py"]["bytes"]) == len(head_source if baseline else files["kinocut/edit.py"])
    assert ("kinocut/new.py" in inventory) is not baseline
    with (output / "runtime-allocation.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == summary["runtime_files"]
    assert {category: sum(int(row[category]) for row in rows) for category in audit.CATEGORIES} == total
    assert json.loads(capsys.readouterr().out) == {
        key: summary[key] for key in ("runtime_files", "tracked_files_inventoried", "totals", "percent")
    }


def test_audit_functions_fit_repository_size_limit(audit):
    tree = ast.parse(Path(audit.__file__).read_text(encoding="utf-8"))
    oversized = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno - node.lineno + 1 > 80
    ]
    assert oversized == []
