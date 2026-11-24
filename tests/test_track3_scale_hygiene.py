"""Regressions for storage and media hot paths with bounded work."""

import errno
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import cas, open_project


def test_resolve_reuses_verified_identity_when_opted_in_and_verifies_by_default(tmp_path, monkeypatch):
    project = open_project(tmp_path / "project")
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    record = cas.ingest_blob(project, source)
    hasher = Mock(wraps=hashlib.sha256)
    monkeypatch.setattr(cas, "hashlib", SimpleNamespace(sha256=hasher))
    # Default verify_content=True always hashes fresh bytes.
    blob = cas.resolve_blob(project, record.digest)
    assert cas.resolve_blob(project, record.digest) == blob
    assert hasher.call_count == 2
    # Opt-in verify_content=False reuses verified identity on trusted local POSIX filesystems.
    monkeypatch.setattr(cas, "_device_has_trusted_ctime", lambda _dev: True)
    assert cas.resolve_blob(project, record.digest, verify_content=False) == blob
    assert hasher.call_count == 2
    assert cas.resolve_blob(project, record.digest, verify_content=True) == blob
    assert hasher.call_count == 3
    old = blob.stat()
    blob.write_bytes(b"bad")
    if os.name == "posix":
        os.utime(blob, ns=(old.st_atime_ns, old.st_mtime_ns))
    with pytest.raises(MCPVideoError):
        cas.resolve_blob(project, record.digest)
    assert hasher.call_count == 4


def test_project_maintenance_limits_evictions_and_records_progress(tmp_path):
    project = open_project(tmp_path / "project")
    source = tmp_path / "source"
    records = []
    for content in (b"one", b"two", b"three"):
        source.write_bytes(content)
        records.append(cas.ingest_blob(project, source))
    for record in records:
        receipt = project.collect_cas_garbage(budget_bytes=0, max_blobs=1)
        assert receipt.deleted_digests == (record.digest,)
        assert receipt.deleted_bytes == record.byte_size
    assert project.collect_cas_garbage(budget_bytes=0, max_blobs=1) is None


def test_snapshot_append_resumes_after_short_kernel_copy(tmp_path, monkeypatch):
    from kinocut.projectstore import store

    records = tmp_path / "records.jsonl"
    records.write_bytes(b'"original"\r\n')
    first = True

    def short_copy(src, dest, count):
        nonlocal first
        if first:
            first = False
            return os.write(dest, os.read(src, 3))
        raise OSError(errno.EXDEV, "kernel copy unavailable")

    monkeypatch.setattr(os, "copy_file_range", short_copy, raising=False)
    store._atomic_append(records, '"next"')
    assert not first
    assert records.read_bytes() == b'"original"\r\n"next"\n'


def test_each_receipt_replacement_retains_only_its_current_witness(tmp_path):
    from kinocut.output_policy import output_operation
    from kinocut.projectstore.receipt_ownership import durable_receipt_ownership
    from kinocut.workflow.receipt import _write_receipt

    target = tmp_path / "receipt.json"
    for attempt in range(2):
        with output_operation(), durable_receipt_ownership(target):
            for stage in range(5):
                _write_receipt({"stage": stage, "attempt": attempt}, str(target), tmp_path, overwrite=True)
                (witness,) = (tmp_path / ".receipt.json.ownership").iterdir()
                assert witness.samefile(target)


def test_ledger_skips_real_stage_and_invalidates_after_external_replacement(tmp_path, monkeypatch):
    from kinocut import output_ledger as ledger
    from kinocut.ffmpeg_helpers import _atomic_output, _owns_operation_output, _open_staged_writer

    monkeypatch.setenv("KINOCUT_STATE_DIR", str(tmp_path / "state"))
    final = tmp_path / "result.mp4"
    with _atomic_output(str(final)) as stage:
        assert _owns_operation_output(stage)
        assert not ledger.owns(stage)
        with _open_staged_writer(stage) as stream:
            stream.write(b"output")
    path = Path(ledger._ledger_path())
    assert [json.loads(row)["path"] for row in path.read_text().splitlines()] == [str(final)]
    parse = Mock(wraps=json.loads)
    monkeypatch.setattr(ledger, "json", SimpleNamespace(loads=parse))
    assert ledger.owns(str(final)) and ledger.owns(str(final))
    assert parse.call_count == 1
    replacement = tmp_path / "replacement"
    replacement.write_text(path.read_text().replace("result", "absent"))
    os.utime(replacement, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns))
    replacement.replace(path)
    assert not ledger.owns(str(final))
    assert parse.call_count == 2


def test_vectorized_pcm24_sign_extension_downmix_and_partial_tail():
    np = pytest.importorskip("numpy")
    from kinocut.audio_engine.core import _pcm_to_float

    samples = [-8388608, 8388607, -1, -256, 65536, 0]
    pcm = b"".join(sample.to_bytes(3, "little", signed=True) for sample in samples) + b"\x00"
    expected = np.array(samples, dtype=float).reshape(-1, 2).mean(axis=1) / 8388607
    np.testing.assert_array_equal(_pcm_to_float(pcm, 3, 2), expected)


def test_combined_quality_matches_independent_decodes(sample_video, monkeypatch):
    from kinocut import engine_compare_quality as quality

    single = {
        metric: quality.compare_quality(sample_video, sample_video, [metric]).metrics[metric]
        for metric in ("psnr", "ssim")
    }
    call = Mock(wraps=quality._run_command)
    monkeypatch.setattr(quality, "_run_command", call)
    assert quality.compare_quality(sample_video, sample_video).metrics == single
    assert call.call_count == 1


@pytest.mark.parametrize("operation", ["gate", "grade", "match"])
def test_still_packages_do_not_retain_a_batch_of_decoded_sources(tmp_path, monkeypatch, operation):
    from importlib import import_module

    image = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    module = import_module(f"kinocut.still_plates.{operation}")
    source_paths = [tmp_path / f"source_{index}.png" for index in range(8)]
    for path in source_paths:
        image.new("RGB", (8, 8), color=(100, 110, 105)).save(path)
    original = module.load_rgb_array
    sources = []

    def observe(path):
        array = original(path)
        sources.append(weakref.ref(array))
        assert sum(ref() is not None for ref in sources) <= 3
        return array

    monkeypatch.setattr(module, "load_rgb_array", observe)
    options = {"hero": source_paths[0]} if operation != "gate" else {}
    result = getattr(module, f"still_{operation}")(inputs=source_paths, output_dir=tmp_path / "out", **options)
    assert Path(result["receipt_path"]).is_file()


def test_still_grade_preflights_destination_input_alias_without_overwriting(tmp_path):
    image = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    from kinocut.still_plates.grade import still_grade

    first = tmp_path / "plate.png"
    second = tmp_path / "plate_graded.png"
    image.new("RGB", (8, 8), color=(10, 20, 30)).save(first)
    image.new("RGB", (12, 12), color=(40, 50, 60)).save(second)
    before = second.read_bytes()
    with pytest.raises(MCPVideoError):
        still_grade(inputs=[first, second], output_dir=tmp_path)
    assert second.read_bytes() == before


def test_cas_and_ledger_detect_tampering_even_with_frozen_stat(tmp_path, monkeypatch):
    from kinocut import output_ledger as ledger

    project = open_project(tmp_path / "project")
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    record = cas.ingest_blob(project, source)
    blob = cas.resolve_blob(project, record.digest)
    frozen_blob_stat = blob.stat()
    blob.write_bytes(b"xyz")
    # Even if an untrusted filesystem reports identical stat metadata, default resolve_blob rejects tampering,
    # and opt-in verify_content=False rejects tampering when device ctime isn't trusted.
    monkeypatch.setattr(cas, "_device_has_trusted_ctime", lambda _dev: False)
    monkeypatch.setattr(cas.os, "fstat", lambda _fd: frozen_blob_stat)
    with pytest.raises(MCPVideoError):
        cas.resolve_blob(project, record.digest)
    with pytest.raises(MCPVideoError):
        cas.resolve_blob(project, record.digest, verify_content=False)

    monkeypatch.setenv("KINOCUT_STATE_DIR", str(tmp_path / "state"))
    out = tmp_path / "out.mp4"
    out.write_bytes(b"123")
    ledger.record_output(str(out))
    assert ledger.owns(str(out))
    lpath = Path(ledger._ledger_path())
    old_lstat = lpath.stat()
    lpath.write_text(lpath.read_text().replace("out.mp4", "alt.mp4"))
    os.utime(lpath, ns=(old_lstat.st_atime_ns, old_lstat.st_mtime_ns))
    assert not ledger.owns(str(out))
    # Literal U+2028 inside JSON string must not be split as a line break.
    sep_out = tmp_path / "line\u2028sep.mp4"
    sep_out.write_bytes(b"123")
    st = sep_out.stat()
    row = f'{{"path":"{sep_out}","id":[{st.st_dev},{st.st_ino},{st.st_size},{st.st_mtime_ns}]}}\n'
    lpath.write_text(row, encoding="utf-8")
    assert ledger.owns(str(sep_out))


def test_still_grade_rejects_zero_byte_lut_output(tmp_path, monkeypatch):
    image = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    from kinocut.errors import ProcessingError
    from kinocut.still_plates import grade

    src = tmp_path / "plate.png"
    lut = tmp_path / "look.cube"
    out_dir = tmp_path / "out"
    image.new("RGB", (8, 8), color=(100, 110, 120)).save(src)
    lut.write_text("LUT_3D_SIZE 2\n", encoding="utf-8")
    # Simulate FFmpeg succeeding without writing bytes into the pre-created atomic stage file.
    monkeypatch.setattr(grade, "_run_ffmpeg", lambda _args: None)
    with pytest.raises(ProcessingError):
        grade.still_grade(inputs=[src], output_dir=out_dir, lut_path=lut)
    assert not (out_dir / "plate_graded.png").exists()
    assert not (out_dir / "still_grade_receipt.json").exists()


def test_receipt_witness_prune_eio_is_best_effort(tmp_path, monkeypatch):
    from kinocut.output_policy import output_operation
    from kinocut.projectstore.receipt_ownership import durable_receipt_ownership
    from kinocut.workflow.receipt import _write_receipt

    target = tmp_path / "receipt.json"
    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.parent.name == ".receipt.json.ownership":
            raise OSError(errno.EIO, "simulated I/O error")
        return real_unlink(self, *args, **kwargs)

    with output_operation(), durable_receipt_ownership(target):
        _write_receipt({"stage": 1}, str(target), tmp_path, overwrite=True)
        monkeypatch.setattr(Path, "unlink", flaky_unlink)
        _write_receipt({"stage": 2}, str(target), tmp_path, overwrite=True)
    assert json.loads(target.read_text())["stage"] == 2
