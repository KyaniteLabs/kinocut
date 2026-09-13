"""A sound-only patch must execute hosted validation and packaging checks."""

import fnmatch
from pathlib import Path
import re
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name):
    return (ROOT / ".github" / "workflows" / name).read_text()


@pytest.mark.parametrize("workflow", ["ci.yml", "pr-safety.yml"])
def test_sound_sources_trigger_every_code_and_docker_classifier(workflow):
    patterns = re.findall(r"grep -Eq '([^']+)'", _workflow(workflow))
    assert patterns, "no classifier expressions were inspected"
    for pattern in patterns:
        for path, expected in [
            ("kinocut_sound/public/dub_job.py", True),
            ("kinocut_sound/mix/_wav.py", True),
            ("docs/notes.md", False),
        ]:
            assert bool(re.search(pattern, path)) is expected, (workflow, pattern, path)


@pytest.mark.parametrize("workflow", ["ci.yml", "pr-safety.yml"])
def test_sound_package_is_in_every_existing_lint_and_format_gate(workflow):
    inspected = 0
    for command in _workflow(workflow).splitlines():
        if "ruff check " in command or "ruff format " in command:
            inspected += 1
            assert "kinocut_sound/" in shlex.split(command), command
    assert inspected >= 2


def test_sound_source_changes_trigger_integration_prs():
    workflow = _workflow("integration-smoke.yml")
    trigger = workflow.split("  pull_request:", 1)[1].split("\nconcurrency:", 1)[0]
    paths = re.findall(r'"([^"\n]+)"', trigger)
    assert any(fnmatch.fnmatchcase("kinocut_sound/public/dub_job.py", pattern) for pattern in paths)
