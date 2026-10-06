"""Git hygiene diagnostics include untracked work and never prescribe destructive cleanup."""

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git-professional-audit.sh"


def test_untracked_work_is_not_reported_clean(tmp_path):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=10
        )

    git("init", "-b", "main")
    git(
        "-c",
        "user.name=Test Contributor",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "Fixture",
    )
    (tmp_path / "untracked.txt").write_text("owned test fixture")
    result = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert "Working tree has uncommitted changes" in result.stdout
    assert "Working tree is clean" not in result.stdout
    assert "registered worktree" in result.stdout
    assert result.returncode == 0  # Local-only repositories report the absent remote as a warning.


def test_audit_does_not_recommend_pruning_unknown_work():
    assert "git remote prune" not in SCRIPT.read_text()
