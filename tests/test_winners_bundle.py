"""Tests for the Sinter winners-bundle envelope (fail-closed verification)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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
