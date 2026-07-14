"""Focused checks for the repository-readiness Dependabot policy."""

import importlib.util
from pathlib import Path


def load_audit_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "repo-readiness-audit.py"
    spec = importlib.util.spec_from_file_location("repo_readiness_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dependabot_is_explicitly_disabled_when_config_is_absent(tmp_path, monkeypatch):
    audit = load_audit_module()
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    assert audit.dependabot_groups_by_ecosystem() is None


def test_dependabot_groups_are_read_when_config_is_present(tmp_path, monkeypatch):
    audit = load_audit_module()
    dependabot = tmp_path / ".github" / "dependabot.yml"
    dependabot.parent.mkdir()
    dependabot.write_text(
        """version: 2
updates:
  - package-ecosystem: uv
    directory: / 
    schedule:
      interval: weekly
    groups:
      python-runtime:
        patterns: ["*"]
  - package-ecosystem: github-actions
    directory: / 
    schedule:
      interval: weekly
    groups:
      github-actions:
        patterns: ["*"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    assert audit.dependabot_groups_by_ecosystem() == {
        ("uv", "/"): {"python-runtime"},
        ("github-actions", "/"): {"github-actions"},
    }
