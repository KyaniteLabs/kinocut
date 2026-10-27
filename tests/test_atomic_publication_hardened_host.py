"""Publication must survive hosts that deny a read-open of the filesystem root.

Hardened hosts (seccomp/LSM policies, some container runtimes) refuse
``os.open("/", os.O_RDONLY | os.O_DIRECTORY)`` with ``PermissionError``.
The atomic-publication path anchored its ancestry walk on that read-open,
so on such hosts every output write failed with:

    Atomic output could not preserve directory identity: PermissionError

The walk only needs the root as an *anchor*; the descriptor is never read
from. ``O_PATH`` satisfies that (it grants no read permission) while keeping
every descendant component opened with ``O_NOFOLLOW`` relative to its parent.
"""

import errno
import os

import pytest

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_output, _open_staged_writer, _reset_operation_inputs


@pytest.fixture(autouse=True)
def fresh_paths():
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _deny_root_read_open(monkeypatch):
    """Simulate a host that refuses a read-open of the filesystem root.

    The global ``os.open`` is replaced for the duration of the test, so the
    ``os.supports_dir_fd`` capability set is extended with the replacement:
    ``kinocut.atomic_publication`` selects the descriptor-anchored
    implementation by testing ``os.open in os.supports_dir_fd``.
    """
    from kinocut import atomic_publication

    real_open = os.open

    def guarded(path, flags, *args, **kwargs):
        if str(path) == os.path.sep and flags & os.O_RDONLY and not flags & os.O_PATH:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    monkeypatch.setattr(os, "supports_dir_fd", set(os.supports_dir_fd) | {guarded})
    assert atomic_publication.os is os


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-anchored creation")
@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="O_PATH required")
def test_publication_succeeds_when_root_read_open_is_denied(tmp_path, monkeypatch):
    _deny_root_read_open(monkeypatch)
    output = tmp_path / "nested" / "delivery.mp4"
    with _atomic_output(str(output)) as staged, _open_staged_writer(staged) as stream:
        stream.write(b"complete delivery on a hardened host")
    assert output.read_bytes() == b"complete delivery on a hardened host"
    assert not list(tmp_path.rglob(".kinocut_tmp_*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-anchored creation")
@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="O_PATH required")
def test_root_anchor_fallback_uses_path_mode(tmp_path, monkeypatch):
    from kinocut import atomic_publication

    seen = {}
    real_open = os.open

    def recording(path, flags, *args, **kwargs):
        if str(path) == os.path.sep:
            seen["flags"] = flags
        return real_open(path, flags, *args, **kwargs)

    _deny_root_read_open(monkeypatch)
    monkeypatch.setattr(atomic_publication.os, "open", recording)
    descriptor = atomic_publication._open_root_descriptor()
    try:
        assert seen["flags"] & os.O_PATH
        assert os.fstat(descriptor).st_mode
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.name != "posix", reason="POSIX hostile ancestry fixture")
@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="O_PATH required")
def test_hostile_ancestry_symlink_still_blocked_on_hardened_hosts(tmp_path, monkeypatch):
    """The fallback must not weaken the no-follow guarantee."""
    from kinocut import atomic_publication

    _deny_root_read_open(monkeypatch)
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
