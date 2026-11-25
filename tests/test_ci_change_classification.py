"""Execute hosted change classifiers against real Git pathname semantics."""

import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
# ci.yml's classify step delegates the code/docker rules to this script.
CI_SCOPE = Path(__file__).resolve().parents[1] / "scripts" / "ci_scope.py"
pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("git") is None,
    reason="Hosted classifiers execute with POSIX Bash and Git",
)


def _classification_script(workflow):
    lines = (WORKFLOWS / workflow).read_text().splitlines()
    step = next(index for index, line in enumerate(lines) if line.strip() == "- id: classify")
    start = next(index for index in range(step + 1, len(lines)) if lines[index].strip() == "run: |")
    indentation = len(lines[start]) - len(lines[start].lstrip())
    body = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            break
        body.append(line)
    script = textwrap.dedent("\n".join(body))
    script = script.replace("${{ github.event.pull_request.base.sha }}", "${FIXTURE_PR_BASE_SHA:-}")
    script = script.replace("${{ github.event.before }}", "${FIXTURE_BASE_SHA}")
    for expression in ("github.sha", "github.event.pull_request.head.sha"):
        script = script.replace("${{ " + expression + " }}", "${FIXTURE_HEAD_SHA}")
    assert script and "${{" not in script
    return script


class _Repository:
    def __init__(self, directory):
        self.directory = directory
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            LC_ALL="C",
        )
        self.git("init", "-q", "--initial-branch=fixture")
        self.write("README.md")
        self.base = self.commit()

    def git(self, *arguments):
        result = subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgSign=false",
                *arguments,
            ],
            cwd=self.directory,
            env=self.environment,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout

    def write(self, filename):
        path = self.directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture content\n")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "Fixture snapshot")
        return self.git("rev-parse", "HEAD").decode().strip()


@pytest.fixture
def repository(tmp_path):
    directory = tmp_path / "repository"
    directory.mkdir()
    return _Repository(directory)


@pytest.fixture(params=["ci.yml"])
def workflow(request):
    return request.param


def _classify(repository, workflow, tmp_path, head, base=None, pr_base=""):
    # The real workflow runs from a full checkout; mirror the classifier it calls.
    (repository.directory / "scripts").mkdir(exist_ok=True)
    shutil.copy(CI_SCOPE, repository.directory / "scripts" / "ci_scope.py")
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    output = tmp_path / "github-output"
    environment = repository.environment | {
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(output),
        "FIXTURE_BASE_SHA": repository.base if base is None else base,
        "FIXTURE_PR_BASE_SHA": pr_base,
        "FIXTURE_HEAD_SHA": head,
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _classification_script(workflow)],
        cwd=repository.directory,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert list(runner_temp.iterdir()) == [], "Classifier left its private pathname list behind"
    values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return result, values


def _assert_classification(result, values, workflow, code, docker):
    assert result.returncode == 0, result.stderr
    expected = {"code": str(code).lower()}
    if workflow == "ci.yml":
        expected["docker"] = str(docker).lower()
    assert values == expected


@pytest.mark.parametrize(
    "path,ci_code,pr_code,docker",
    [
        ("kinocut/feature.py", True, True, True),
        ("kinocut_sound/feature.py", True, True, True),
        ("kinocut_sound/public/dub_job.py", True, True, True),
        ("kinocut_sound/mix/_wav.py", True, True, True),
        ("tests/test_fixture.py", True, True, False),
        ("mcp_video.py", True, True, True),
        ("pyproject.toml", True, True, True),
        ("uv.lock", True, True, True),
        ("Dockerfile", True, False, True),
        (".dockerignore", False, False, True),
        (".github/workflows/ci.yml", True, True, True),
        (".github/actions/cache-ffmpeg/action.yml", True, False, False),
        (".github/workflows/integration-smoke.yml", True, True, False),
        (".github/workflows/mcpb.yml", True, True, False),
        (".github/workflows/publish.yml", True, True, False),
        (".github/workflows/future-control.yml", True, True, False),
        (".github/scripts/check-hyperframes-results.py", True, True, False),
        (".github/scripts/check-built-artifacts.py", True, True, False),
        (".github/scripts/future-guard.py", True, True, False),
        ("scripts/annotate-pytest-failures.py", True, True, False),
        ("docs/guide.md", False, False, False),
        ("CHANGELOG.md", False, False, False),
    ],
)
def test_classifier_preserves_selected_root_mappings(repository, workflow, tmp_path, path, ci_code, pr_code, docker):
    repository.write(path)
    result, values = _classify(repository, workflow, tmp_path, repository.commit())
    _assert_classification(result, values, workflow, ci_code if workflow == "ci.yml" else pr_code, docker)


@pytest.mark.parametrize(
    "path,code,docker",
    [
        ("kinocut/雪.py", True, True),
        ("kinocut/tab\tname.py", True, True),
        ("kinocut/new\nname.py", True, True),
        ("kinocut/back\\slash.py", True, True),
        ('kinocut/quote"name.py', True, True),
        (".github/workflows/雪\tname.yml", True, False),
        (".github/scripts/new\nname.py", True, False),
        ("docs/safe\nkinocut/fake.py", False, False),
        ("docs/雪\tname.md", False, False),
        ('docs/back\\quote"name.md', False, False),
    ],
)
def test_classifier_handles_literal_pathnames_without_line_splitting(
    repository, workflow, tmp_path, path, code, docker
):
    repository.write(path)
    result, values = _classify(repository, workflow, tmp_path, repository.commit())
    _assert_classification(result, values, workflow, code, docker)


def test_deleted_runtime_still_requires_validation(repository, workflow, tmp_path):
    repository.write("kinocut/removed.py")
    repository.base = repository.commit()
    (repository.directory / "kinocut/removed.py").unlink()
    result, values = _classify(repository, workflow, tmp_path, repository.commit())
    _assert_classification(result, values, workflow, True, True)


@pytest.mark.parametrize(
    "source,destination,runtime",
    [
        ("kinocut/moved.py", "docs/moved.py", True),
        ("docs/moved.py", "kinocut/moved.py", True),
        ("docs/before.md", "docs/after.md", False),
    ],
)
def test_renames_validate_both_removed_and_added_root_paths(
    repository, workflow, tmp_path, source, destination, runtime
):
    repository.write(source)
    repository.base = repository.commit()
    destination_path = repository.directory / destination
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    (repository.directory / source).rename(destination_path)
    head = repository.commit()
    assert repository.git("diff", "--name-only", "-z", repository.base, head, "--").split(b"\0") == [
        destination.encode(),
        b"",
    ], "Fixture must actually exercise Git's rename detection"
    result, values = _classify(repository, workflow, tmp_path, head)
    _assert_classification(result, values, workflow, runtime, runtime)


@pytest.mark.parametrize("first_path", [".github/scripts/check-hyperframes-results.py", "mcp_video.py", None])
def test_large_changes_preserve_early_matches_without_pipefail(repository, workflow, tmp_path, first_path):
    for index in range(500):
        repository.write(f"docs/{index:04d}-{'d' * 132}.md")
    if first_path is not None:
        repository.write(first_path)
        repository.git("config", "diff.orderFile", "fixture-order")
        (repository.directory / "fixture-order").write_text(first_path + "\ndocs/*\n")
    head = repository.commit()
    changed = repository.git("diff", "--no-renames", "--name-only", "-z", repository.base, head, "--")
    assert len(changed) >= 67_544
    if first_path is not None:
        assert changed.split(b"\0")[0] == first_path.encode()
    result, values = _classify(repository, workflow, tmp_path, head)
    _assert_classification(result, values, workflow, first_path is not None, first_path == "mcp_video.py")


@pytest.mark.parametrize("base", ["", "0" * 40])
def test_master_without_event_base_validates_parent_difference(repository, tmp_path, base):
    repository.write("kinocut/feature.py")
    result, values = _classify(repository, "ci.yml", tmp_path, repository.commit(), base=base)
    _assert_classification(result, values, "ci.yml", True, True)


def test_master_without_parent_fails_closed(repository, tmp_path):
    result, values = _classify(repository, "ci.yml", tmp_path, repository.base, base="")
    assert result.returncode != 0
    assert values == {}


@pytest.mark.parametrize("path", ["kinocut/feature.py", "docs/guide.md"])
def test_unreachable_event_base_runs_every_check(repository, tmp_path, path):
    """A force-pushed PR's `before` commit is gone from the checkout: validate everything, never skip (#690)."""
    repository.write(path)
    result, values = _classify(repository, "ci.yml", tmp_path, repository.commit(), base="f" * 40)
    _assert_classification(result, values, "ci.yml", True, True)
    assert "running every check" in result.stdout


def test_pr_uses_pull_request_base_not_latest_push_delta(repository, tmp_path):
    """A code commit followed by a docs-only push on a PR must still classify code=true."""
    pr_base = repository.base
    repository.write("kinocut/feature.py")
    prior_head = repository.commit()
    repository.write("docs/guide.md")
    latest_head = repository.commit()
    result, values = _classify(repository, "ci.yml", tmp_path, latest_head, base=prior_head, pr_base=pr_base)
    _assert_classification(result, values, "ci.yml", True, True)


@pytest.mark.parametrize(
    "path",
    [
        "docs/public_claims.json",
        "README.md",
        "llms.txt",
        "qa/runner.py",
        "scripts/run_full_suite.py",
        "server.json",
        "Dockerfile.ci",
    ],
)
def test_claims_qa_scripts_and_manifests_trigger_code_suite(repository, tmp_path, path):
    target = repository.directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("updated fixture content\n")
    result, values = _classify(repository, "ci.yml", tmp_path, repository.commit())
    assert result.returncode == 0, result.stderr
    assert values["code"] == "true"
