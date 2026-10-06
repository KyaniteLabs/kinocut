"""Descriptor-only index movement, packet preservation and malformed-index rejection."""

import os
import json
import shutil
import struct

import pytest

from kinocut.errors import MCPVideoError
from kinocut.mp4_faststart import _rebuild, relocate_index
from kinocut.staged_writers import _darwin_faststart_command

requires_positional_io = pytest.mark.skipif(
    not all(hasattr(os, name) for name in ("pread", "pwrite")), reason="Darwin relocation requires POSIX positional I/O"
)


def box(kind, payload):
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def index(offset, kind=b"stco"):
    code = ">I" if kind == b"stco" else ">Q"
    payload = box(kind, b"\x00" * 4 + struct.pack(">I", 1) + struct.pack(code, offset))
    for container in (b"stbl", b"minf", b"mdia", b"trak", b"moov"):
        payload = box(container, payload)
    return payload


@pytest.mark.parametrize("kind", [b"stco", b"co64"])
@requires_positional_io
def test_relocation_preserves_packets_and_moves_index_before_media(tmp_path, kind):
    header = box(b"ftyp", b"isom0000")
    packets = b"encoded packets" * 100000
    media = box(b"mdat", packets)
    old_index = index(len(header) + 8, kind)
    path = tmp_path / "owned.mp4"
    path.write_bytes(header + media + old_index)
    with path.open("r+b") as stream:
        relocate_index(stream.fileno())
    new_index = index(len(header) + len(old_index) + 8, kind)
    assert path.read_bytes() == header + new_index + media
    with path.open("r+b") as stream:
        relocate_index(stream.fileno())
    assert path.read_bytes() == header + new_index + media  # Already early: no second mutation.


def test_large_chunk_offsets_promote_to_co64_and_recompute_index_size():
    offset = (1 << 32) - 20
    original = index(offset)
    promoted = _rebuild(original, len(original), 0, 1 << 33)
    assert len(promoted) == len(original) + 4
    final = _rebuild(original, len(promoted), 0, 1 << 33)
    assert final == index(offset + len(promoted), b"co64")


@pytest.mark.parametrize(
    "content", [b"short", box(b"mdat", b"data"), box(b"moov", b"broken"), struct.pack(">I4s", 999, b"moov")]
)
@requires_positional_io
def test_malformed_layout_does_not_modify_staged_bytes(tmp_path, content):
    path = tmp_path / "invalid.mp4"
    path.write_bytes(content)
    with path.open("r+b") as stream, pytest.raises(MCPVideoError) as error:
        relocate_index(stream.fileno())
    assert error.value.code == "invalid_faststart_output"
    assert path.read_bytes() == content


@requires_positional_io
def test_unlinked_owned_inode_needs_no_path_reopen(tmp_path):
    path = tmp_path / "owned.mp4"
    media = box(b"mdat", b"packets")
    old_index = index(8)
    path.write_bytes(media + old_index)
    with path.open("r+b") as stream:
        path.unlink()
        relocate_index(stream.fileno())
        assert os.pread(stream.fileno(), len(media) + len(old_index), 0) == index(8 + len(old_index)) + media


@requires_positional_io
def test_extended_box_headers_keep_exact_media_bytes(tmp_path):
    media = struct.pack(">I4sQ", 1, b"mdat", 23) + b"packets"
    ordinary = index(16, b"co64")
    old_index = struct.pack(">I4sQ", 1, b"moov", len(ordinary) + 8) + ordinary[8:]
    path = tmp_path / "extended.mp4"
    path.write_bytes(media + old_index)
    with path.open("r+b") as stream:
        relocate_index(stream.fileno())
    ordinary = index(16 + len(old_index), b"co64")
    expected = struct.pack(">I4sQ", 1, b"moov", len(ordinary) + 8) + ordinary[8:]
    assert path.read_bytes() == expected + media


@pytest.mark.parametrize(
    "invalid_index",
    [
        box(b"moov", box(b"cmov", b"compressed")),
        box(b"moov", box(b"stco", b"\x00" * 4 + struct.pack(">I", 1))),
        index(999),
        box(b"moov", box(b"moov", box(b"moov", box(b"moov", box(b"moov", box(b"moov", b"")))))),
    ],
)
@requires_positional_io
def test_unsupported_index_preserves_original_staging_bytes(tmp_path, invalid_index):
    content = box(b"mdat", b"packets") + invalid_index
    path = tmp_path / "invalid.mp4"
    path.write_bytes(content)
    with path.open("r+b") as stream, pytest.raises(MCPVideoError):
        relocate_index(stream.fileno())
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "flags, enabled",
    [
        ("+faststart", True),
        ("+faststart-faststart", False),
        ("+faststart+use_metadata_tags", True),
        ("+frag_keyframe", False),
    ],
)
def test_darwin_command_preserves_other_muxer_flags(monkeypatch, flags, enabled):
    import kinocut.staged_writers as writers

    monkeypatch.setattr(writers.sys, "platform", "darwin")
    command = ["ffmpeg", "-i", "input", "-movflags", flags, "output.mp4"]
    rewritten, relocate = _darwin_faststart_command(command)
    assert relocate is enabled
    assert rewritten == ([*command[:-1], "-movflags", "-faststart", command[-1]] if enabled else command)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="Real muxer required")
@pytest.mark.parametrize("suffix", [".mp4", ".mov", ".m4a"])
@requires_positional_io
def test_real_muxer_faststart_preserves_every_encoded_packet(tmp_path, suffix, monkeypatch):
    from kinocut.ffmpeg_helpers import _atomic_output, _run_command, _run_ffmpeg
    import kinocut.staged_writers as writers

    monkeypatch.setattr(writers.sys, "platform", "darwin")
    source, output = tmp_path / ("source" + suffix), tmp_path / ("output" + suffix)
    picture = ["-f", "lavfi", "-i", "testsrc2=size=64x64:rate=4"] if suffix != ".m4a" else []
    codecs = ["-c:v", "libx264"] if picture else []
    _run_ffmpeg(
        [
            *picture,
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            *codecs,
            "-c:a",
            "aac",
            str(source),
        ]
    )
    with _atomic_output(str(output)) as staged:
        _run_ffmpeg(["-i", str(source), "-map", "0", "-c", "copy", "-movflags", "+faststart", staged])
    _run_ffmpeg(["-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"])
    data = output.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")

    def packets(path):
        result = _run_command(
            ["ffprobe", "-v", "error", "-show_packets", "-show_data_hash", "sha256", "-of", "json", str(path)],
            timeout=10,
        )
        return [(item["stream_index"], item["data_hash"]) for item in json.loads(result.stdout)["packets"]]

    assert packets(source) == packets(output)


@pytest.mark.parametrize("runner", ["_run_ffmpeg", "_run_command"])
def test_failed_producer_keeps_original_error_and_never_relocates(tmp_path, monkeypatch, runner):
    import subprocess
    import kinocut.bounded_process as bounded
    import kinocut.ffmpeg_helpers as helpers
    import kinocut.mp4_faststart as faststart
    import kinocut.staged_writers as writers

    monkeypatch.setattr(writers.sys, "platform", "darwin")
    monkeypatch.setattr(
        bounded, "run_bounded", lambda *_args, **_kw: subprocess.CompletedProcess([], 1, "", "muxer failed")
    )
    monkeypatch.setattr(faststart, "relocate_index", lambda *_: pytest.fail("failed producer must not relocate"))
    output = tmp_path / "output.mp4"
    output.write_bytes(b"original")
    with pytest.raises(MCPVideoError), helpers._atomic_output(str(output)) as staged:
        args = ["-movflags", "+faststart", staged]
        if runner == "_run_command":
            helpers._run_command(["ffmpeg", *args], timeout=10)
        else:
            helpers._run_ffmpeg(args)
    assert output.read_bytes() == b"original"


def test_unsigned_later_movflags_replace_faststart(monkeypatch):
    import kinocut.staged_writers as writers

    monkeypatch.setattr(writers.sys, "platform", "darwin")
    command = ["ffmpeg", "-i", "input", "-movflags", "+faststart", "-movflags", "use_metadata_tags", "output.mp4"]
    assert _darwin_faststart_command(command) == (command, False)
