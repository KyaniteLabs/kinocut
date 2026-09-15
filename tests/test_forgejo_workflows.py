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


def test_lint_runs_in_prebuilt_base_image_and_fails_closed_before_clone():
    """Lint jobs run in the baked base image; no per-job apt, fail-closed clone.

    The prebuilt `ci-images-base` image carries git/curl/python3/ca-certificates,
    so the workflow must not apt-install anything. Colima/G2 images cannot clone
    Forgejo anonymously: `secrets.GITHUB_TOKEN` is not always injected, so
    `github.token` is the fallback and an empty token must exit before cloning.
    Runner workspaces are not always empty, so clone into WORKDIR, not `.`.
    """
    lint = _lint_job_text()
    assert "ci-images-base:v1" in lint, "lint must run in the prebuilt base image"
    assert "apt-get" not in lint, "toolchain is baked into the image; no per-job apt"
    token_gate = lint.find('if [ -z "$TOKEN" ]')
    assert token_gate != -1, "lint must refuse an empty clone token"
    assert "secrets.GITHUB_TOKEN" in lint
    assert "github.token" in lint
    workdir = lint.find("WORKDIR=")
    clone = lint.find("git clone --depth")
    assert workdir != -1 and 'mkdir -p "$WORKDIR"' in lint and 'cd "$WORKDIR"' in lint
    assert clone != -1 and token_gate < clone and workdir < clone, "token gate must fail before cloning"
    assert "lint-checkout" in lint
    assert "set -x" not in lint.split("Install ruff")[0]
    assert "working-directory: src" in lint


def test_claims_live_does_not_share_the_light_runner_with_lint():
    """Master-push claims oracle on `light` starves lint's apt-get curl install."""
    text = (WORKFLOWS / "claims-live.yml").read_text(encoding="utf-8")
    assert "runs-on: heavy" in text
    assert "runs-on: light" not in text


def test_lint_checkout_posts_fail_closed_status_without_runtime_apt():
    """Baked curl posts the lint-checkout status; ruff installs into its own venv.

    The status POST must be visible to the API-only debugger (context
    `lint-checkout`), use `curl --fail` so a failed POST fails the step, and sit
    inside the checkout step's EXIT trap so failures are reported. The heavy
    apt-get bootstrap this used to interleave with is gone with the prebuilt image.
    """
    lint = _lint_job_text()
    assert "curl --fail" in lint
    post = lint.find('"context":"lint-checkout"')
    assert post != -1, "expected JSON lint-checkout payload"
    trap = lint.find("trap 'post_checkout_status error")
    assert trap != -1 and trap < lint.find("git clone --depth"), "checkout failures must POST an error status"
    checkout = lint.split("Install ruff")[0]
    assert "shell: bash" in checkout
    assert "${desc:0:" not in checkout
    assert "timeout-minutes: 10" in checkout
    assert "apt-get" not in lint, "no apt bootstrap left once the toolchain is baked"


def test_heavy_ci_jobs_and_ffmpeg_assets_target_x86_64_runner():
    """G2 is x86_64; its dedicated label must never receive ARM64 assets."""
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    _lint, separator, heavy_jobs = workflow.partition("\n  test:")
    assert separator
    assert heavy_jobs.count("runs-on: x86-heavy") == 3
    assert "runs-on: arm64-heavy" not in heavy_jobs
    assert "linuxarm64" not in heavy_jobs
    assert set(re.findall(r"ffmpeg_asset: ([^\s]+)", heavy_jobs)) == {
        "ffmpeg-n6.1.3-linux64-gpl-6.1.tar.xz",
        "ffmpeg-n7.1.5-1-g7d0e842004-linux64-gpl-7.1.tar.xz",
        "ffmpeg-n8.1.2-21-gce3c09c101-linux64-gpl-8.1.tar.xz",
    }
