"""Read-only source analysis for dedicated video rescue."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue.analyzer import analyze_source


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_analyzer_is_read_only_and_emits_explicit_units(tmp_path, sample_video):
    source = tmp_path / "input.mp4"
    shutil.copy2(sample_video, source)
    before = _sha256(source)

    result = analyze_source(str(source), tmp_path, tmp_path / "previews")

    assert _sha256(source) == before
    assert result.source.sha256 == f"sha256:{before}"
    assert all(
        metric.unit and metric.definition
        for finding in result.findings
        for metric in finding.evidence
    )
    assert all(
        metric.value is None
        for finding in result.findings
        for metric in finding.evidence
        if not metric.available
    )
    assert [preview.timestamp_ratio for preview in result.previews] == [0.1, 0.5, 0.9]
    assert all((tmp_path / preview.path).is_file() for preview in result.previews)


def test_corrupt_input_fails_before_preview_creation(tmp_path):
    source = tmp_path / "bad.mov"
    source.write_bytes(b"not media")

    with pytest.raises(MCPVideoError) as caught:
        analyze_source(str(source), tmp_path, tmp_path / "previews")

    assert caught.value.code == "invalid_rescue_input"
    assert not (tmp_path / "previews").exists()


def test_source_must_be_confined_to_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.mov"
    outside.write_bytes(b"not media")

    with pytest.raises(MCPVideoError) as caught:
        analyze_source(str(outside), workspace, workspace / "previews")

    assert caught.value.code == "invalid_rescue_input"
    assert not (workspace / "previews").exists()
