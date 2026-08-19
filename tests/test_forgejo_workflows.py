"""Contracts for Forgejo workflows that the Actions log API does not expose."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".forgejo" / "workflows"
_GIT_PUSH_FF_ONLY = re.compile(r"git\s+push\b[^\n]*--ff-only")


def _workflow_texts() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))}


def _lint_job_text() -> str:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    lint, sep, _rest = workflow.partition("\n  test:")
    assert sep, "ci.yml must define a lint job before test"
    return lint


def test_workflows_never_pass_ff_only_to_git_push():
    """Runner Git 2.43 rejects `git push --ff-only` (unknown option) in ~13s."""
    offenders = {
        name: "git push --ff-only" for name, text in _workflow_texts().items() if _GIT_PUSH_FF_ONLY.search(text)
    }
    assert offenders == {}


def test_lint_checkout_fails_closed_before_apt_and_clones_into_empty_dir():
    """Invisible ~40s lint: token/clone fail after apt, no ruff status, tests skip.

    Colima images cannot clone Forgejo anonymously. `secrets.GITHUB_TOKEN` is not
    always injected; `github.token` is the automatic job token. Runner workspaces
    are not always empty, so clone into `.` is not reliable.
    """
    lint = _lint_job_text()
    token_gate = lint.find('if [ -z "$TOKEN" ]')
    apt = lint.find("apt-get update")
    workdir = lint.find("WORKDIR=")
    assert token_gate != -1, "lint must refuse an empty clone token"
    assert apt != -1 and token_gate < apt, "empty token must fail before apt-get"
    assert "github.token" in lint
    clone = lint.find("git clone --depth")
    assert workdir != -1 and 'mkdir -p "$WORKDIR"' in lint and 'cd "$WORKDIR"' in lint
    assert clone != -1 and workdir < clone
    assert "lint-checkout" in lint
    assert "set -x" not in lint.split("Install ruff")[0]
    assert "working-directory: src" in lint
