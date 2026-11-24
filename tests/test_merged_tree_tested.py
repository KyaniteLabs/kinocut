"""A master push may skip re-testing only a tree its pull request head already passed."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "merged_tree_tested.py"
SPEC = importlib.util.spec_from_file_location("merged_tree_tested", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REPO = "KyaniteLabs/kinocut"
PUSHED = "a" * 40
HEAD = "b" * 40


def _fake(*, pulls=None, trees=None, runs=None, jobs=None):
    pulls = (
        [
            {
                "number": 7,
                "merged_at": "2026-11-22T00:00:00Z",
                "merge_commit_sha": PUSHED,
                "base": {"ref": "master"},
                "head": {"sha": HEAD},
            }
        ]
        if pulls is None
        else pulls
    )
    trees = {PUSHED: "t1", HEAD: "t1"} if trees is None else trees
    runs = (
        [
            {
                "id": 1,
                "run_number": 5,
                "run_attempt": 1,
                "head_sha": HEAD,
                "event": "pull_request",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        if runs is None
        else runs
    )
    jobs = (
        [
            {
                "name": "Test (Python 3.13)",
                "status": "completed",
                "conclusion": "success",
                "steps": [{"name": "Run tests with coverage", "conclusion": "success"}],
            }
        ]
        if jobs is None
        else jobs
    )

    def fetch(path):
        if path.endswith("/pulls"):
            return pulls
        if "/git/commits/" in path:
            return {"tree": {"sha": trees[path.rsplit("/", 1)[1]]}}
        if "/actions/workflows/ci.yml/runs?" in path:
            assert "event=pull_request" in path and f"head_sha={HEAD}" in path
            return {"workflow_runs": runs}
        if "/actions/runs/" in path and "/jobs?" in path:
            return {"jobs": jobs}
        raise AssertionError(path)

    return fetch


def _decide(**kwargs):
    return MODULE.decide(_fake(**kwargs), REPO, PUSHED, "ci.yml")[0]


def test_identical_tree_with_green_pull_request_run_is_tested():
    assert _decide() is True


def test_skipped_pytest_on_pr_does_not_skip_master():
    skipped_jobs = [
        {
            "name": "Test (Python 3.13)",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Skip tests", "conclusion": "success"},
                {"name": "Run tests with coverage", "conclusion": "skipped"},
            ],
        }
    ]
    assert _decide(jobs=skipped_jobs) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pulls": []},
        {
            "pulls": [
                {
                    "number": 7,
                    "merged_at": None,
                    "merge_commit_sha": PUSHED,
                    "base": {"ref": "master"},
                    "head": {"sha": HEAD},
                }
            ]
        },
        {
            "pulls": [
                {
                    "number": 7,
                    "merged_at": "x",
                    "merge_commit_sha": "c" * 40,
                    "base": {"ref": "master"},
                    "head": {"sha": HEAD},
                }
            ]
        },
        {
            "pulls": [
                {
                    "number": 7,
                    "merged_at": "x",
                    "merge_commit_sha": PUSHED,
                    "base": {"ref": "release"},
                    "head": {"sha": HEAD},
                }
            ]
        },
        {"trees": {PUSHED: "t1", HEAD: "t2"}},
        {"runs": []},
        {
            "runs": [
                {
                    "id": 1,
                    "run_number": 5,
                    "run_attempt": 1,
                    "head_sha": HEAD,
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        },
        {
            "runs": [
                {
                    "id": 1,
                    "run_number": 5,
                    "run_attempt": 1,
                    "head_sha": HEAD,
                    "event": "pull_request",
                    "status": "in_progress",
                    "conclusion": None,
                }
            ]
        },
        {
            "runs": [
                {
                    "id": 1,
                    "run_number": 5,
                    "run_attempt": 1,
                    "head_sha": HEAD,
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 2,
                    "run_number": 6,
                    "run_attempt": 1,
                    "head_sha": HEAD,
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "cancelled",
                },
            ]
        },
    ],
)
def test_anything_short_of_proof_runs_the_suite(kwargs):
    assert _decide(**kwargs) is False


def test_api_failure_prints_tested_false(capsys):
    def broken(path):
        raise OSError("network down")

    assert MODULE.main(["--repository", REPO, "--sha", PUSHED, "--workflow", "ci.yml"], fetch=broken) == 0
    assert capsys.readouterr().out == "tested=false\n"


def test_workflows_skip_master_pushes_only_through_the_helper():
    for name, workflow in (
        ("ci.yml", "ci.yml"),
        ("mcpb.yml", "mcpb.yml"),
        ("integration-smoke.yml", "integration-smoke.yml"),
    ):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert (
            f'merged_tree_tested.py --repository "$GITHUB_REPOSITORY" --sha "$GITHUB_SHA" --workflow {workflow}' in text
        )
        assert "if: github.event_name == 'push'" in text
        assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
