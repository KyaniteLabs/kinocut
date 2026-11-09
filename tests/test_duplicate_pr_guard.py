"""Pure-function checks for the advisory duplicate PR guard (.github/scripts)."""

import datetime as dt
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "duplicate-pr-guard.py"
_spec = importlib.util.spec_from_file_location("duplicate_pr_guard", _PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

CUTOFF = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)


def test_references_collects_issues_and_linear_keys():
    issues, keys = guard.references("Closes #679. Linear klh-340, see KyaniteLabs/other#12 and cursor/klh-309-x")
    assert issues == {679}
    assert keys == {"KLH-340", "KLH-309"}


def test_live_means_open_or_recently_merged():
    assert guard.is_live({"state": "OPEN"}, CUTOFF)
    assert guard.is_live({"state": "MERGED", "mergedAt": "2026-11-09T19:34:09Z"}, CUTOFF)
    assert not guard.is_live({"state": "MERGED", "mergedAt": "2026-10-01T00:00:00Z"}, CUTOFF)
    assert not guard.is_live({"state": "CLOSED", "mergedAt": None}, CUTOFF)


def test_preflight_exit_codes(monkeypatch, capsys):
    claimed = {694: ({"state": "MERGED", "mergedAt": "2026-11-09T19:34:09Z", "title": "ui-capture"}, {"#679"})}
    monkeypatch.setattr(guard, "find_overlaps", lambda repo, text: claimed)
    assert guard.preflight("o/r", "#679") == 1
    monkeypatch.setattr(guard, "find_overlaps", lambda repo, text: {})
    assert guard.preflight("o/r", "#679") == 0

    def unauthenticated(repo, text):
        raise guard.subprocess.CalledProcessError(4, ["gh"], stderr="gh auth login")

    monkeypatch.setattr(guard, "find_overlaps", unauthenticated)
    assert guard.preflight("o/r", "#679") == 2
    assert "UNKNOWN" in capsys.readouterr().out
