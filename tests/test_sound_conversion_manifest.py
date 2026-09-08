"""Private role manifests cannot substitute paths, formats or processing claims."""

import json
import os
import time
import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_conversion_prepare import _prepared_assets
from kinocut_sound.public.mix_conversion_manifest import _load_manifest_fd, _public_projection
from kinocut_sound.public.mix_files import open_root
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.mix_worker import render_to_stage
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project  # noqa: F401


@pytest.fixture
def prepared_conversion(converted_project):  # noqa: F811
    root, payload = converted_project
    request = load_mix_request(payload)
    with open_root(str(root)) as original, _prepared_assets(request, original, time.monotonic() + 20) as prepared:
        yield root, request, prepared


def test_readonly_manifest_and_redacted_projection(prepared_conversion):
    import fcntl

    _root, request, prepared = prepared_conversion
    assert fcntl.fcntl(prepared.manifest_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert _load_manifest_fd(prepared.manifest_fd, request) == prepared.manifest
    projection = _public_projection(prepared.manifest, request)
    assert all("path" not in entry["derived"] for entry in projection["entries"])
    assert [entry["original"]["path"] for entry in projection["entries"]] == ["a.wav", "b.wav"]


@pytest.mark.parametrize(
    "change", ["version", "hash", "missing", "duplicate", "role", "path", "profile", "bool", "unknown", "derived_hash"]
)
def test_forged_manifest_cannot_write_stage(prepared_conversion, change):
    root, request, prepared = prepared_conversion
    value = prepared.manifest.model_dump(mode="json")
    entry = value["entries"][0]
    if change == "version":
        value["private_schema_version"] = 2
    elif change == "hash":
        value["request_hash"] = "sha256:" + "b" * 64
    elif change == "missing":
        value["entries"].pop()
    elif change == "duplicate":
        value["entries"][1] = entry
    elif change == "role":
        entry["binding_id"] = "unknown"
    elif change == "path":
        entry["derived"]["path"] = "../a.wav"
    elif change == "profile":
        entry["backend"]["precision"] = 20
    elif change == "bool":
        entry["guard_frames"] = True
    elif change == "unknown":
        entry["ignored"] = True
    else:
        entry["derived"]["sha256"] = "sha256:" + "b" * 64
    manifest = root / "tampered.json"
    manifest.write_text(json.dumps(value))
    with manifest.open("rb") as raw, (root / "stage").open("wb+") as stage:
        with pytest.raises(MixError):
            render_to_stage(request, prepared.root_fd, stage.fileno(), raw.fileno())
        assert stage.seek(0, 2) == 0


def test_v4_missing_manifest_rejected_before_sources(converted_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker

    _root, request = converted_project
    monkeypatch.setattr(mix_worker, "_sources", lambda *args: pytest.fail("missing manifest reached source reads"))
    with pytest.raises(MixError):
        render_to_stage(request, -1, -1)


def test_legacy_extra_manifest_rejected_before_sources(mix_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker

    _root, request = mix_project
    monkeypatch.setattr(mix_worker, "_sources", lambda *args: pytest.fail("legacy extra descriptor reached sources"))
    with pytest.raises(MixError):
        render_to_stage(request, -1, -1, -1)


def test_derived_symlink_is_rejected(prepared_conversion):
    root, request, prepared = prepared_conversion
    entry = prepared.manifest.entries[0]
    os.unlink(entry.derived.path, dir_fd=prepared.root_fd)
    os.symlink(str(root / "a.wav"), entry.derived.path, dir_fd=prepared.root_fd)
    with (root / "stage").open("wb+") as stage:
        with pytest.raises(MixError):
            render_to_stage(request, prepared.root_fd, stage.fileno(), prepared.manifest_fd)
        assert stage.seek(0, 2) == 0
