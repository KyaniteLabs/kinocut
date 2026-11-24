"""Behavior at the shared publication boundary."""

import errno
import os
import sys
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.output_ledger import owns
from kinocut.publication import (
    anchored_tree,
    atomic_output,
    open_staged_writer,
    output_operation,
    owns_operation_output,
)


def test_ledger_and_operation_do_not_adopt_an_inode_swapped_after_verification(tmp_path, monkeypatch):
    from kinocut.publication import _files

    final = tmp_path / "delivery.mp4"
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"not our output")
    monkeypatch.setenv("KINOCUT_STATE_DIR", str(tmp_path / "state"))
    record = _files._record_write

    def replace_before_recording(path, info, *, published):
        if published:
            replacement.replace(final)
        record(path, info, published=published)

    monkeypatch.setattr(_files, "_record_write", replace_before_recording)
    with output_operation():
        with atomic_output(str(final)) as stage, open_staged_writer(stage) as stream:
            stream.write(b"our output")
        assert not owns_operation_output(str(final))
        assert not owns(str(final))
    assert final.read_bytes() == b"not our output"


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="requires native directory exchange")
def test_tree_exchange_keeps_old_delivery_visible_until_commit(tmp_path):
    final = tmp_path / "delivery"
    with anchored_tree(final) as stage:
        (stage / "platform").mkdir()
        (stage / "platform" / "manifest.json").write_text("old")
        assert not final.exists()
    original = final.stat()
    with anchored_tree(final, overwrite=True) as stage:
        (stage / "platform").mkdir()
        (stage / "platform" / "manifest.json").write_text("new")
        assert (final / "platform" / "manifest.json").read_text() == "old"
    assert (final / "platform" / "manifest.json").read_text() == "new"
    assert final.stat().st_ino != original.st_ino
    assert list(tmp_path.iterdir()) == [final]


def test_tree_exchange_succeeds_on_windows_via_durable_sibling(tmp_path, monkeypatch):
    from kinocut.publication import _trees

    final = tmp_path / "delivery"
    (final / "platform").mkdir(parents=True)
    (final / "platform" / "manifest.json").write_text("old", encoding="utf-8")
    monkeypatch.setattr(_trees, "os", SimpleNamespace(**{**os.__dict__, "name": "nt"}))
    with anchored_tree(final, overwrite=True) as stage:
        (stage / "platform").mkdir()
        (stage / "platform" / "manifest.json").write_text("new", encoding="utf-8")
    assert (final / "platform" / "manifest.json").read_text(encoding="utf-8") == "new"
    assert list(tmp_path.iterdir()) == [final]


def test_tree_exchange_windows_contested_rollback_preserves_old_package(tmp_path, monkeypatch):
    from kinocut.publication import _trees

    final = tmp_path / "delivery"
    (final / "platform").mkdir(parents=True)
    (final / "platform" / "manifest.json").write_text("old-package", encoding="utf-8")
    real_rename = os.rename

    def contested_rename(src, dst):
        if os.path.basename(str(src)).startswith(".kinocut_package_") and os.fspath(dst) == str(final):
            final.mkdir()
            (final / "rival.txt").write_text("rival", encoding="utf-8")
            raise FileExistsError(errno.EEXIST, "destination claimed by rival")
        return real_rename(src, dst)

    monkeypatch.setattr(
        _trees, "os", SimpleNamespace(**{**os.__dict__, "name": "nt", "rename": staticmethod(contested_rename)})
    )
    with pytest.raises(MCPVideoError) as failure, anchored_tree(final, overwrite=True) as stage:
        (stage / "platform").mkdir()
        (stage / "platform" / "manifest.json").write_text("new-package", encoding="utf-8")
    assert failure.value.code == "package_write_conflict"
    assert (final / "rival.txt").read_text(encoding="utf-8") == "rival"
    preserved = list(tmp_path.glob(".delivery.displaced_*"))
    assert len(preserved) == 1
    assert (preserved[0] / "platform" / "manifest.json").read_text(encoding="utf-8") == "old-package"


def test_thumbnail_supports_bmp_through_atomic_staging(tmp_path):
    from kinocut import engine_thumbnail
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    source = tmp_path / "source.mp4"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    final = tmp_path / "frame.bmp"
    result = engine_thumbnail.thumbnail(str(source), output_path=str(final), smart=False)
    assert result.output_path == str(final)
    assert final.read_bytes().startswith(b"BM")


def test_thumbnail_failure_does_not_truncate_previous_delivery(tmp_path, monkeypatch):
    from kinocut import engine_thumbnail

    source = tmp_path / "source.mp4"
    source.touch()
    final = tmp_path / "frame.jpg"
    final.write_bytes(b"prior frame")
    monkeypatch.setattr(engine_thumbnail, "get_duration", lambda _: 10.0)

    def interrupted(args):
        with open_staged_writer(args[-1]) as stream:
            stream.write(b"incomplete frame")
        assert final.read_bytes() == b"prior frame"
        raise RuntimeError("encoder stopped")

    monkeypatch.setattr(engine_thumbnail, "_run_ffmpeg", interrupted)
    with output_operation(True), pytest.raises(RuntimeError, match="encoder stopped"):
        engine_thumbnail.thumbnail(str(source), output_path=str(final), smart=False)
    assert final.read_bytes() == b"prior frame"
    assert sorted(tmp_path.iterdir()) == [final, source]
