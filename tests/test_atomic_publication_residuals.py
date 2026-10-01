"""Creation and publication failures must not write through hostile ancestry."""

import os

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_output, _open_staged_writer, _reset_operation_inputs


@pytest.fixture(autouse=True)
def fresh_paths():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def test_missing_output_ancestry_is_created_and_published(tmp_path):
    output = tmp_path / "new" / "nested" / "delivery.mp4"
    with _atomic_output(str(output)) as staged, _open_staged_writer(staged) as stream:
        stream.write(b"complete delivery")
    assert output.read_bytes() == b"complete delivery"
    assert not list(tmp_path.rglob(".kinocut_tmp_*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-anchored creation")
def test_planted_missing_ancestor_symlink_cannot_create_files_in_victim(tmp_path, monkeypatch):
    from kinocut import atomic_publication

    safe, victim = tmp_path / "safe", tmp_path / "victim"
    safe.mkdir()
    victim.mkdir()
    marker = victim / "keep.mp4"
    marker.write_bytes(b"prior victim")
    mkdir = os.mkdir

    def plant(path, mode=0o777, *, dir_fd=None):
        if path == "new" and dir_fd is not None:
            os.symlink(str(victim), path, dir_fd=dir_fd)
        return mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(atomic_publication.os, "mkdir", plant)
    with pytest.raises(MCPVideoError) as error, _atomic_output(str(safe / "new" / "nested" / "out.mp4")):
        pytest.fail("hostile ancestry must not reach the writer")
    assert error.value.code == "unsafe_path"
    assert list(victim.iterdir()) == [marker]
    assert marker.read_bytes() == b"prior victim"


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink race fixture")
def test_canonical_target_is_revalidated_before_directory_creation(tmp_path, monkeypatch):
    from kinocut import atomic_publication

    safe, home = tmp_path / "safe", tmp_path / "home"
    safe.mkdir()
    secret = home / ".ssh"
    secret.mkdir(parents=True)
    output = safe / "new" / "out.mp4"
    realpath = os.path.realpath
    calls = 0

    def swapped(path, *args, **kwargs):
        nonlocal calls
        if str(path) == str(output):
            calls += 1
            if calls == 2:
                safe.rmdir()
                safe.symlink_to(secret, target_is_directory=True)
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(atomic_publication.os.path, "realpath", swapped)
    monkeypatch.setattr(atomic_publication.os.path, "expanduser", lambda _: str(home))
    with pytest.raises(MCPVideoError) as error, _atomic_output(str(output)):
        pytest.fail("changed canonical target must not reach writer")
    assert error.value.code == "unsafe_path"
    assert not list(secret.iterdir())


@pytest.mark.skipif(os.name != "posix", reason="POSIX hostile rename fixture")
def test_swap_after_staging_check_is_reported_as_partial_publication(tmp_path, monkeypatch):
    from kinocut import atomic_publication

    final, victim = tmp_path / "delivery.mp4", tmp_path / "victim.mp4"
    final.write_bytes(b"prior delivery")
    victim.write_bytes(b"victim remains intact")
    replace = os.replace

    def swap(source, target, **kwargs):
        if target == final.name:
            staged = tmp_path / source
            staged.unlink()
            staged.symlink_to(victim)
        return replace(source, target, **kwargs)

    monkeypatch.setattr(atomic_publication.os, "replace", swap)
    with (
        pytest.raises(MCPVideoError) as error,
        _atomic_output(str(final)) as staged,
        _open_staged_writer(staged) as stream,
    ):
        stream.write(b"complete descriptor-bound stage")
    assert error.value.code == "partial_output_publication"
    assert error.value.suggested_action["prior_output_preserved"] is False
    assert final.is_symlink()  # No unsafe rollback of another writer's artifact.
    assert victim.read_bytes() == b"victim remains intact"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX anchored directory rename fixture")
def test_directory_swap_during_rename_cannot_certify_a_different_returned_path(tmp_path, monkeypatch):
    from kinocut import atomic_publication

    safe, parked = tmp_path / "safe", tmp_path / "parked"
    safe.mkdir()
    final = safe / "delivery.mp4"
    final.write_bytes(b"prior delivery")
    replace = os.replace

    def swap(source, target, **kwargs):
        if target == final.name:
            safe.rename(parked)
            safe.mkdir()
            final.write_bytes(b"unrelated replacement directory")
        return replace(source, target, **kwargs)

    monkeypatch.setattr(atomic_publication.os, "replace", swap)
    with (
        pytest.raises(MCPVideoError) as error,
        _atomic_output(str(final)) as staged,
        _open_staged_writer(staged) as stream,
    ):
        stream.write(b"complete anchored delivery")
    assert error.value.code == "partial_output_publication"
    assert final.read_bytes() == b"unrelated replacement directory"
    assert (parked / final.name).read_bytes() == b"complete anchored delivery"
    assert not list(tmp_path.rglob(".kinocut_tmp_*"))
