"""A release version change cannot leave native CI selecting an older artifact."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcpb_candidate_paths", ROOT / ".github/scripts/mcpb-artifact-paths.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _candidate(tmp_path: Path, version: str = "1.234.5") -> Path:
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    (tmp_path / f"kinocut-{version}-py3-none-any.whl").write_bytes(b"fixture")
    (tmp_path / f"kinocut-{version}.mcpb").write_bytes(b"fixture")
    return project


def test_selects_the_actual_project_version_instead_of_a_release_literal(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    assert MODULE.candidate_paths(tmp_path, project) == {
        "version": "1.234.5",
        "wheel_file": "kinocut-1.234.5-py3-none-any.whl",
        "bundle_file": "kinocut-1.234.5.mcpb",
    }


@pytest.mark.parametrize("suffix", ["whl", "mcpb"])
def test_stale_extra_artifact_fails_closed(tmp_path: Path, suffix: str) -> None:
    project = _candidate(tmp_path)
    (tmp_path / f"kinocut-0.0.1.{suffix}").write_bytes(b"old")
    with pytest.raises(ValueError, match="exactly one"):
        MODULE.candidate_paths(tmp_path, project)


@pytest.mark.parametrize("suffix", ["whl", "mcpb"])
def test_old_version_as_the_only_artifact_fails_closed(tmp_path: Path, suffix: str) -> None:
    project = _candidate(tmp_path)
    original = next(tmp_path.glob(f"*.{suffix}"))
    original.rename(tmp_path / f"kinocut-0.0.1.{suffix}")
    with pytest.raises(ValueError, match="versions disagree"):
        MODULE.candidate_paths(tmp_path, project)


def test_workflow_passes_the_selected_pair_through_every_native_lane() -> None:
    workflow = (ROOT / ".github/workflows/mcpb.yml").read_text(encoding="utf-8")
    assert "mcpb-artifact-paths.py --directory dist" in workflow
    assert "steps.candidate.outputs.bundle_file" in workflow
    assert workflow.count("needs.build-validate.outputs.bundle_file") == 4
    assert workflow.count("needs.build-validate.outputs.wheel_file") == 2


def test_filename_cannot_inject_an_additional_github_output(tmp_path: Path) -> None:
    project = _candidate(tmp_path)
    wheel = next(tmp_path.glob("*.whl"))
    bad_name = "kinocut-1.234.5-py3-none-any\nforged=1.whl"
    try:
        wheel.rename(tmp_path / bad_name)
    except OSError:
        pytest.skip("platform rejects newline-containing filenames")
    with pytest.raises(ValueError, match="versions disagree"):
        MODULE.candidate_paths(tmp_path, project)
