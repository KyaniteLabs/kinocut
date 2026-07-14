"""Tests for the project-store layout rules (Plan 00 Task 3).

Layout is pure path arithmetic: content-addressed asset paths derived from an
``asset_id``, sanitized filename labels, record/index/lock locations, and a
root-containment defense. No filesystem writes happen here — every path is a
project-relative :class:`PurePosixPath`, and containment is checked against a
resolved root so a crafted name or digest can never escape ``.kinocut/``.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from kinocut.contracts._errors import INVALID_RECORD
from kinocut.errors import MCPVideoError
from kinocut.projectstore import layout

_DIGEST = "a" * 64
_ASSET_ID = f"sha256:{_DIGEST}"


def test_asset_path_is_content_addressed_and_project_relative():
    rel = layout.asset_relative_path(_ASSET_ID, "clip01.mp4")
    assert rel == PurePosixPath(".kinocut", "assets", "sha256", _DIGEST, "clip01.mp4")
    # Project-relative: no leading slash, tilde, or drive letter.
    assert not str(rel).startswith(("/", "~", "\\"))


def test_asset_path_rejects_malformed_asset_id():
    with pytest.raises(MCPVideoError) as excinfo:
        layout.asset_relative_path("not-a-hash", "clip.mp4")
    assert excinfo.value.code == INVALID_RECORD


def test_sanitize_name_keeps_basename_and_strips_traversal():
    # A traversing, separator-laden name collapses to a safe label only.
    assert layout.sanitize_name("../../etc/passwd") == "passwd"
    assert layout.sanitize_name("a/b/clip 01!.mp4") == "clip_01_.mp4"
    # Never empty, never a dotfile, never "." / "..".
    assert layout.sanitize_name("") == "asset"
    assert layout.sanitize_name("..") == "asset"
    assert not layout.sanitize_name(".hidden").startswith(".")


def test_sanitized_asset_path_neutralizes_traversal_in_name():
    rel = layout.asset_relative_path(_ASSET_ID, "../../../evil.mp4")
    assert rel == PurePosixPath(".kinocut", "assets", "sha256", _DIGEST, "evil.mp4")


def test_records_path_is_kind_scoped_jsonl():
    assert layout.records_relative_path("clip_verdict") == PurePosixPath(".kinocut", "records", "clip_verdict.jsonl")


def test_records_path_rejects_unsafe_kind():
    with pytest.raises(MCPVideoError) as excinfo:
        layout.records_relative_path("../escape")
    assert excinfo.value.code == INVALID_RECORD


def test_contained_path_allows_in_tree_and_rejects_escape(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    inside = layout.contained_path(root, PurePosixPath(".kinocut", "records", "x.jsonl"))
    assert isinstance(inside, Path)
    assert str(inside).startswith(str(root.resolve()))
    with pytest.raises(MCPVideoError) as excinfo:
        layout.contained_path(root, "../../outside.txt")
    assert excinfo.value.code == INVALID_RECORD
