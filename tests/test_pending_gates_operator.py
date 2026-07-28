from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/kinocut-pending.py"


def _module():
    spec = importlib.util.spec_from_file_location("kinocut_pending", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issue(number: int, *labels: str) -> dict:
    return {"number": number, "labels": [{"name": label} for label in labels]}


def test_pending_operator_keeps_human_and_release_gates_explicit() -> None:
    module = _module()
    issues = {
        number: _issue(number, "blocked:post-release")
        for number in module.EXPECTED_POST_RELEASE
    }

    gates = module._build_gates(issues, "installed; daemon unavailable")
    by_name = {gate.name: gate for gate in gates}

    assert by_name["Post-release backlog"].state == "BLOCKED"
    assert by_name["Post-release backlog"].issues == module.EXPECTED_POST_RELEASE
    assert by_name["Compositor queue"].state == "QUEUED"
    assert by_name["Directory submission"].state == "NOT AUTHORIZED"
    assert by_name["Real-user evidence"].state == "NEEDS REAL USERS"
    assert by_name["Dependency dashboard"].state == "AUTOMATIC"
    assert "working Docker daemon" in by_name["Runner activation"].next_action


def test_pending_operator_detects_changed_tracker_state() -> None:
    module = _module()
    issues = {
        number: _issue(number, "blocked:post-release")
        for number in module.EXPECTED_POST_RELEASE
    }
    issues[73] = _issue(73)

    gates = module._build_gates(issues, "ready (fixture)")

    backlog = next(gate for gate in gates if gate.name == "Post-release backlog")
    assert backlog.state == "BLOCKED"
    assert 73 not in backlog.issues


def test_pending_operator_json_contract_is_read_only(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "_git_state", lambda: {"origin": "forgejo", "master_sync": "0\t0"})
    monkeypatch.setattr(module, "_docker_state", lambda: "unavailable")
    monkeypatch.setattr(module, "_fetch_issues", lambda: {})
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--json"])

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["read_only"] is True
    assert payload["tracker_live"] is True
    assert "Release actions authorized" in payload["authority_update_template"]


def test_pending_operator_surfaces_new_issue_instead_of_hiding_it() -> None:
    module = _module()
    issues = {999: _issue(999)}

    gates = module._build_gates(issues, "unavailable")

    review = next(gate for gate in gates if gate.name == "New or uncategorized issues")
    assert review.issues == (999,)
    assert review.state == "REVIEW"


def test_pending_operator_compacts_issue_ranges_for_humans() -> None:
    module = _module()

    assert module._format_issues((63, 64, 65, 67, 70, 71)) == "#63-65, #67, #70-71"


def test_copy_paste_mode_skips_status_calls(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "_git_state", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--copy-paste"])

    assert module.main() == 0
    assert capsys.readouterr().out.startswith("Kinocut authority update:")
