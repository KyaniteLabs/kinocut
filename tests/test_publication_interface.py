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


def test_tree_exchange_fails_closed_on_windows(tmp_path, monkeypatch):
    from kinocut.publication import _anchor

    final = tmp_path / "delivery"
    final.mkdir()
    original = final.stat()
    with pytest.raises(MCPVideoError) as failure, anchored_tree(final, overwrite=True):
        monkeypatch.setattr(_anchor, "os", SimpleNamespace(name="nt", stat=os.stat, fstat=os.fstat, close=os.close))
    assert failure.value.code == "shorts_package_publish_failed"
    assert failure.value.__cause__.errno == errno.ENOTSUP
    assert final.stat().st_ino == original.st_ino
    assert list(tmp_path.iterdir()) == [final]


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
