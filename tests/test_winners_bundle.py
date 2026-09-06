"""Tests for the Sinter winners-bundle envelope (fail-closed verification)."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import kinocut.winners_bundle as winners_bundle_module
from kinocut.errors import ValidationError
from kinocut.winners_bundle import (
    _canonical_manifest_bytes,
    stage_bundle,
    verify_bundle,
    write_bundle,
)

_HEX = hashlib.sha256(b"artifact").hexdigest()
_EVENT = hashlib.sha256(b"event").hexdigest()


def _make_payload(tmp_path: Path, name: str = "winner.glsl", body: bytes = b"void main() {}") -> Path:
    payload = tmp_path / name
    payload.write_bytes(body)
    return payload


def _artifact_spec(payload_source: Path) -> dict:
    return {
        "artifact_id": _HEX,
        "event_id": _EVENT,
        "domain": "glsl",
        "axes": "D=2.0 A=2.0 R=3.0 N=2.0 | judges: test | defects: 0",
        "level": "S",
        "license": "MIT",
        "judges": ["gemini-3.7", "minimax-m3"],
        "payload_source": str(payload_source),
    }


def _bundle(tmp_path: Path) -> Path:
    dest = tmp_path / "bundle"
    write_bundle(dest, [_artifact_spec(_make_payload(tmp_path))], "2026-08-31T00:00:00Z")
    return dest


def _rewrite_manifest(bundle: Path, mutate) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    mutate(manifest)
    manifest["envelope_sha256"] = hashlib.sha256(_canonical_manifest_bytes(manifest)).hexdigest()
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


class TestWriteVerifyRoundtrip:
    def test_roundtrip(self, tmp_path):
        bundle = _bundle(tmp_path)
        receipt = verify_bundle(bundle)
        assert receipt.schema_version == "sinter.winners/0.1"
        assert receipt.exported_at == "2026-08-31T00:00:00Z"
        assert len(receipt.envelope_sha256) == 64
        (artifact,) = receipt.artifacts
        assert artifact.artifact_id == _HEX and artifact.event_id == _EVENT
        assert artifact.domain == "glsl" and artifact.level == "S"
        assert artifact.license == "MIT"
        assert artifact.judges == ["gemini-3.7", "minimax-m3"]
        assert artifact.payload_path == "payload/winner.glsl"
        assert artifact.payload_bytes == len(b"void main() {}")

    def test_two_artifacts_roundtrip(self, tmp_path):
        dest = tmp_path / "bundle"
        second = tmp_path / "winner2.glsl"
        second.write_bytes(b"float t;")
        write_bundle(
            dest,
            [
                _artifact_spec(_make_payload(tmp_path)),
                _artifact_spec(second) | {"artifact_id": hashlib.sha256(b"b").hexdigest()},
            ],
            "2026-08-31T00:00:00Z",
        )
        assert len(verify_bundle(dest).artifacts) == 2

    def test_roundtrip_from_unresolved_platform_temporary_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assert str(root) == temporary
            source = _make_payload(root)
            dest = root / "bundle"

            receipt = write_bundle(dest, [_artifact_spec(source)], "2026-08-31T00:00:00Z")

            assert verify_bundle(dest).envelope_sha256 == receipt.envelope_sha256


class TestWriterFailsClosed:
    """The writer must not emit a self-invalidating bundle (CodeRabbit, PR #489)."""

    def test_writer_rejects_unknown_license(self, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path)) | {"license": "AGPL-9.9"}
        with pytest.raises(ValidationError, match="license"):
            write_bundle(tmp_path / "b1", [spec], "2026-08-31T00:00:00Z")

    def test_writer_rejects_missing_license_not_keyerror(self, tmp_path):
        spec = dict(_artifact_spec(_make_payload(tmp_path)))
        del spec["license"]
        with pytest.raises(ValidationError, match="license"):
            write_bundle(tmp_path / "b2", [spec], "2026-08-31T00:00:00Z")

    def test_writer_rejects_empty_judges(self, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path)) | {"judges": []}
        with pytest.raises(ValidationError, match="judges"):
            write_bundle(tmp_path / "b3", [spec], "2026-08-31T00:00:00Z")


class TestVerifyFailsClosed:
    def test_missing_manifest(self, tmp_path):
        with pytest.raises(ValidationError, match=r"no manifest\.json"):
            verify_bundle(tmp_path / "empty")

    def test_invalid_json_manifest(self, tmp_path):
        bundle = _bundle(tmp_path)
        (bundle / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError, match="not valid JSON"):
            verify_bundle(bundle)

    def test_unknown_schema_version(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m.update(schema_version="sinter.winners/0.2"))
        with pytest.raises(ValidationError, match="schema_version"):
            verify_bundle(bundle)

    def test_envelope_digest_mismatch(self, tmp_path):
        bundle = _bundle(tmp_path)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        manifest["envelope_sha256"] = "0" * 64
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValidationError, match="envelope_sha256"):
            verify_bundle(bundle)

    def test_tampered_payload(self, tmp_path):
        bundle = _bundle(tmp_path)
        verify_bundle(bundle)
        (bundle / "payload" / "winner.glsl").write_bytes(b"void main() { /* evil */ }")
        with pytest.raises(ValidationError, match="digest mismatch"):
            verify_bundle(bundle)

    def test_unlisted_extra_payload_file(self, tmp_path):
        bundle = _bundle(tmp_path)
        (bundle / "payload" / "rogue.txt").write_text("x")
        with pytest.raises(ValidationError, match="not listed"):
            verify_bundle(bundle)

    def test_missing_listed_payload(self, tmp_path):
        bundle = _bundle(tmp_path)
        (bundle / "payload" / "winner.glsl").unlink()
        with pytest.raises(ValidationError, match="listed payload missing"):
            verify_bundle(bundle)

    def test_traversal_payload_path_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(
            bundle,
            lambda m: m["artifacts"][0]["payload"].update(path="payload/../manifest.json"),
        )
        with pytest.raises(ValidationError, match="bundle-relative"):
            verify_bundle(bundle)

    def test_unknown_license_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].update(license="AGPL-9.9"))
        with pytest.raises(ValidationError, match="license"):
            verify_bundle(bundle)

    def test_missing_license_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].pop("license"))
        with pytest.raises(ValidationError, match="missing required fields"):
            verify_bundle(bundle)

    def test_historical_judges_null_accepted(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].update(judges=None))
        receipt = verify_bundle(bundle)
        assert receipt.artifacts[0].judges is None

    def test_empty_judges_list_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].update(judges=[]))
        with pytest.raises(ValidationError, match="judges"):
            verify_bundle(bundle)

    def test_non_hex_identity_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].update(artifact_id="not-a-hash"))
        with pytest.raises(ValidationError, match="artifact_id"):
            verify_bundle(bundle)

    def test_empty_artifacts_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m.update(artifacts=[]))
        with pytest.raises(ValidationError, match="non-empty list"):
            verify_bundle(bundle)


class TestStageBundle:
    def test_stage_copies_verified_payload(self, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"
        receipt = stage_bundle(bundle, staged)
        assert (staged / "winner.glsl").read_bytes() == b"void main() {}"
        assert receipt.staged_dir == str(staged)

    def test_stage_refuses_tampered_bundle(self, tmp_path):
        bundle = _bundle(tmp_path)
        (bundle / "payload" / "winner.glsl").write_bytes(b"tampered")
        with pytest.raises(ValidationError):
            stage_bundle(bundle, tmp_path / "staged")

    def test_stage_rejects_unlisted_symlinked_directory(self, tmp_path):
        bundle = _bundle(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "unlisted.txt").write_text("synthetic")
        _symlink_or_skip(bundle / "payload" / "alias", outside, directory=True)

        staged = tmp_path / "staged"
        with pytest.raises(ValidationError, match="symlink"):
            stage_bundle(bundle, staged)
        assert not staged.exists()

    def test_stage_rejects_destination_root_symlink(self, tmp_path):
        bundle = _bundle(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "sentinel.txt").write_text("preserve")
        staged = tmp_path / "staged"
        _symlink_or_skip(staged, outside, directory=True)

        with pytest.raises(ValidationError, match="symlink"):
            stage_bundle(bundle, staged)
        assert (outside / "sentinel.txt").read_text() == "preserve"
        assert sorted(path.name for path in outside.iterdir()) == ["sentinel.txt"]

    def test_stage_rejects_destination_entry_symlink(self, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"
        staged.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("preserve")
        _symlink_or_skip(staged / "winner.glsl", outside)

        with pytest.raises(ValidationError):
            stage_bundle(bundle, staged)
        assert outside.read_text() == "preserve"
        assert (staged / "winner.glsl").is_symlink()

    def test_stage_rejects_unverified_copy_and_leaves_no_destination(self, monkeypatch, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"

        def corrupt_copy(source, destination, expected_digest, expected_bytes):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"corrupt")

        with monkeypatch.context() as scoped:
            scoped.setattr("kinocut.winners_bundle._copy_verified_payload", corrupt_copy, raising=False)
            with pytest.raises(ValidationError, match="copied payload"):
                stage_bundle(bundle, staged)
        assert not staged.exists()
        receipt = stage_bundle(bundle, staged)
        assert receipt.staged_dir == str(staged)
        assert (staged / "winner.glsl").read_bytes() == b"void main() {}"

    def test_stage_merges_into_existing_destination(self, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"
        staged.mkdir()
        sentinel = staged / "sentinel.txt"
        sentinel.write_text("preserve")

        receipt = stage_bundle(bundle, staged)

        assert receipt.staged_dir == str(staged)
        assert sentinel.read_text() == "preserve"
        assert (staged / "winner.glsl").read_bytes() == b"void main() {}"

    def test_stage_accepts_existing_empty_destination(self, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"
        staged.mkdir()

        receipt = stage_bundle(bundle, staged)

        assert receipt.staged_dir == str(staged)
        assert (staged / "winner.glsl").read_bytes() == b"void main() {}"

    def test_stage_returns_no_receipt_until_final_copy_verification_passes(self, monkeypatch, tmp_path):
        bundle = _bundle(tmp_path)
        staged = tmp_path / "staged"

        def fail_final_verification(staged_path, receipt):
            raise ValidationError("winners_bundle", "synthetic final verification failure")

        with monkeypatch.context() as scoped:
            scoped.setattr("kinocut.winners_bundle._verify_staged_payloads", fail_final_verification)
            with pytest.raises(ValidationError, match="final verification"):
                stage_bundle(bundle, staged)
        assert not staged.exists()

    def test_stage_accepts_caller_selected_destination_parent_alias(self, tmp_path):
        bundle = _bundle(tmp_path)
        outside = tmp_path / "outside-parent"
        outside.mkdir()
        alias = tmp_path / "alias-parent"
        _symlink_or_skip(alias, outside, directory=True)

        receipt = stage_bundle(bundle, alias / "staged")

        assert receipt.staged_dir == str(alias / "staged")
        assert (outside / "staged" / "winner.glsl").read_bytes() == b"void main() {}"

    def test_stage_merge_failure_rolls_back_and_retry_succeeds(self, monkeypatch, tmp_path):
        bundle = tmp_path / "bundle"
        first = _make_payload(tmp_path, "first.glsl", b"new first")
        second = _make_payload(tmp_path, "second.glsl", b"new second")
        write_bundle(
            bundle,
            [_artifact_spec(first), _artifact_spec(second) | {"artifact_id": hashlib.sha256(b"second").hexdigest()}],
            "2026-08-31T00:00:00Z",
        )
        staged = tmp_path / "staged"
        staged.mkdir()
        (staged / "first.glsl").write_bytes(b"old first")
        (staged / "sentinel.txt").write_text("preserve")
        original_replace = winners_bundle_module._replace_payload

        def fail_second_publish(source, destination):
            if Path(destination) == staged / "second.glsl":
                raise OSError("synthetic publish failure")
            original_replace(source, destination)

        with monkeypatch.context() as scoped:
            scoped.setattr("kinocut.winners_bundle._replace_payload", fail_second_publish)
            with pytest.raises(ValidationError, match="merge failed"):
                stage_bundle(bundle, staged)
        assert (staged / "first.glsl").read_bytes() == b"old first"
        assert not (staged / "second.glsl").exists()
        assert (staged / "sentinel.txt").read_text() == "preserve"

        stage_bundle(bundle, staged)
        assert (staged / "first.glsl").read_bytes() == b"new first"
        assert (staged / "second.glsl").read_bytes() == b"new second"
        assert (staged / "sentinel.txt").read_text() == "preserve"

    def test_stage_parent_creation_failure_removes_partial_directories(self, monkeypatch, tmp_path):
        bundle = _bundle(tmp_path)
        source = bundle / "payload" / "winner.glsl"
        nested = bundle / "payload" / "nested" / "deeper" / source.name
        nested.parent.mkdir(parents=True)
        source.rename(nested)
        _rewrite_manifest(
            bundle, lambda m: m["artifacts"][0]["payload"].update(path="payload/nested/deeper/winner.glsl")
        )
        staged = tmp_path / "staged"
        staged.mkdir()
        (staged / "sentinel.txt").write_text("preserve")
        original_mkdir = Path.mkdir

        def fail_deeper(path, *args, **kwargs):
            if path == staged / "nested" / "deeper":
                raise OSError("synthetic parent failure")
            return original_mkdir(path, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "mkdir", fail_deeper)
            with pytest.raises(ValidationError, match="parent"):
                stage_bundle(bundle, staged)
        assert not (staged / "nested").exists()
        assert (staged / "sentinel.txt").read_text() == "preserve"


class TestWriteGuards:
    def test_write_rejects_empty_artifacts(self, tmp_path):
        # CodeRabbit #473: write_bundle must not emit an envelope that
        # verify_bundle would immediately reject.
        dest = tmp_path / "bundle"
        with pytest.raises(ValidationError, match="non-empty list"):
            write_bundle(dest, [], "2026-08-31T00:00:00Z")
        assert not dest.exists()

    def test_write_rejects_nonempty_payload_dir(self, tmp_path):
        # CodeRabbit #473: rewriting into a used destination would leave stale
        # payload files the new manifest does not list; fail closed instead.
        dest = tmp_path / "bundle"
        write_bundle(dest, [_artifact_spec(_make_payload(tmp_path, "a.glsl"))], "2026-08-31T00:00:00Z")
        with pytest.raises(ValidationError, match="not empty"):
            write_bundle(
                dest,
                [_artifact_spec(_make_payload(tmp_path, "b.glsl", b"other"))],
                "2026-08-31T00:00:00Z",
            )

    def test_write_rejects_missing_payload_source_without_touching_destination(self, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path))
        del spec["payload_source"]
        dest = tmp_path / "bundle"

        with pytest.raises(ValidationError, match="payload_source"):
            write_bundle(dest, [spec], "2026-08-31T00:00:00Z")
        assert not dest.exists()

    def test_write_validates_second_artifact_before_touching_destination(self, tmp_path):
        first = _artifact_spec(_make_payload(tmp_path, "first.glsl"))
        second = _artifact_spec(_make_payload(tmp_path, "second.glsl")) | {"license": "unknown"}
        dest = tmp_path / "bundle"

        with pytest.raises(ValidationError, match="license"):
            write_bundle(dest, [first, second], "2026-08-31T00:00:00Z")
        assert not dest.exists()

    def test_write_copy_failure_leaves_no_destination(self, monkeypatch, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path))
        dest = tmp_path / "bundle"

        def fail_copy(source, destination, expected_digest, expected_bytes):
            raise OSError("synthetic copy failure")

        with monkeypatch.context() as scoped:
            scoped.setattr("kinocut.winners_bundle._copy_verified_payload", fail_copy, raising=False)
            with pytest.raises(ValidationError, match="copy"):
                write_bundle(dest, [spec], "2026-08-31T00:00:00Z")
        assert not dest.exists()
        receipt = write_bundle(dest, [spec], "2026-08-31T00:00:00Z")
        assert receipt.artifacts[0].payload_bytes == len(b"void main() {}")

    def test_write_preserves_unrelated_files_in_existing_destination(self, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path))
        dest = tmp_path / "bundle"
        dest.mkdir()
        (dest / "payload").mkdir()
        sentinel = dest / "sentinel.txt"
        sentinel.write_text("preserve")

        receipt = write_bundle(dest, [spec], "2026-08-31T00:00:00Z")

        assert receipt.artifacts[0].payload_path == "payload/winner.glsl"
        assert sentinel.read_text() == "preserve"
        assert verify_bundle(dest).envelope_sha256 == receipt.envelope_sha256

    def test_write_rejects_destination_root_symlink(self, tmp_path):
        spec = _artifact_spec(_make_payload(tmp_path))
        outside = tmp_path / "outside"
        outside.mkdir()
        alias = tmp_path / "bundle-alias"
        _symlink_or_skip(alias, outside, directory=True)

        with pytest.raises(ValidationError, match="symlink"):
            write_bundle(alias, [spec], "2026-08-31T00:00:00Z")
        assert not (outside / "manifest.json").exists()

    def test_write_rejects_duplicate_names_before_touching_destination(self, tmp_path):
        source = _make_payload(tmp_path)
        dest = tmp_path / "bundle"

        with pytest.raises(ValidationError, match="duplicate payload filename"):
            write_bundle(
                dest,
                [_artifact_spec(source), _artifact_spec(source)],
                "2026-08-31T00:00:00Z",
            )
        assert not dest.exists()

    def test_write_rejects_symlinked_payload_source(self, tmp_path):
        outside = _make_payload(tmp_path, "outside.glsl")
        alias = tmp_path / "alias.glsl"
        _symlink_or_skip(alias, outside)
        dest = tmp_path / "bundle"

        with pytest.raises(ValidationError, match="symlink"):
            write_bundle(dest, [_artifact_spec(alias)], "2026-08-31T00:00:00Z")
        assert not dest.exists()

    def test_write_accepts_caller_selected_source_parent_alias(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        source = outside / "winner.glsl"
        source.write_bytes(b"void main() {}")
        alias = tmp_path / "source-alias"
        _symlink_or_skip(alias, outside, directory=True)
        dest = tmp_path / "bundle"

        receipt = write_bundle(dest, [_artifact_spec(alias / source.name)], "2026-08-31T00:00:00Z")

        assert verify_bundle(dest).envelope_sha256 == receipt.envelope_sha256

    def test_write_accepts_existing_empty_destination(self, tmp_path):
        dest = tmp_path / "bundle"
        dest.mkdir()

        receipt = write_bundle(
            dest,
            [_artifact_spec(_make_payload(tmp_path))],
            "2026-08-31T00:00:00Z",
        )

        assert receipt.artifacts[0].payload_path == "payload/winner.glsl"
        assert verify_bundle(dest).envelope_sha256 == receipt.envelope_sha256


class TestSymlinkContainment:
    def test_verify_rejects_listed_payload_symlink(self, tmp_path):
        bundle = _bundle(tmp_path)
        outside = tmp_path / "outside.glsl"
        outside.write_bytes(b"void main() {}")
        listed = bundle / "payload" / "winner.glsl"
        listed.unlink()
        _symlink_or_skip(listed, outside)

        with pytest.raises(ValidationError, match="symlink"):
            verify_bundle(bundle)

    def test_verify_rejects_symlinked_payload_directory(self, tmp_path):
        bundle = _bundle(tmp_path)
        payload = bundle / "payload"
        outside = tmp_path / "outside-payload"
        payload.rename(outside)
        _symlink_or_skip(payload, outside, directory=True)

        with pytest.raises(ValidationError, match="symlink"):
            verify_bundle(bundle)

    def test_verify_rejects_symlinked_bundle_root(self, tmp_path):
        bundle = _bundle(tmp_path)
        alias = tmp_path / "bundle-alias"
        _symlink_or_skip(alias, bundle, directory=True)

        with pytest.raises(ValidationError, match="symlink"):
            verify_bundle(alias)

    def test_verify_accepts_caller_selected_bundle_parent_alias(self, tmp_path):
        outside = tmp_path / "outside-parent"
        outside.mkdir()
        bundle = _bundle(outside)
        alias = tmp_path / "bundle-parent-alias"
        _symlink_or_skip(alias, outside, directory=True)

        assert verify_bundle(alias / bundle.name).schema_version == "sinter.winners/0.1"


class TestExactSchema:
    def test_unexpected_manifest_field_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m.update(extra_field=True))
        with pytest.raises(ValidationError, match="unexpected fields"):
            verify_bundle(bundle)

    def test_unexpected_artifact_field_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0].update(score=99))
        with pytest.raises(ValidationError, match="unexpected fields"):
            verify_bundle(bundle)

    def test_unexpected_payload_field_rejected(self, tmp_path):
        bundle = _bundle(tmp_path)
        _rewrite_manifest(bundle, lambda m: m["artifacts"][0]["payload"].update(alg="sha256"))
        with pytest.raises(ValidationError, match="unexpected fields"):
            verify_bundle(bundle)
