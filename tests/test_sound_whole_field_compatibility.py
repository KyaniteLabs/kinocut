"""Strict field boundaries preserve valid values, schema patterns and archives."""

from array import array
import hashlib
from types import SimpleNamespace
import pytest

from kinocut_sound._canonical import BoundedCode, RecordBase
from kinocut_sound.public.mix_request import SourceAsset, load_mix_request
from kinocut_sound.qa.meter import _version
from kinocut_sound.validation import SHA256_PATTERN, RECORD_KIND_PATTERN, CREATED_BY_PATTERN
from kinocut_sound.voice.clone import CloneRenderer
from kinocut_sound.voice.blend import BlendRenderer
from kinocut_sound.mix._wav import pcm_to_wav
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project, make_stereo  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project
from tests.test_sound_rate_conversion_composition import converted_layers


@pytest.mark.parametrize("value", ["a", "A_1:valid.code-2", "a" * 64])
def test_valid_codes_are_not_normalized(value):
    assert BoundedCode(value) == value


def test_code_length_and_prefix_parsers_remain_correct():
    with pytest.raises(ValueError):
        BoundedCode("a" * 65)
    assert _version(b"ffmpeg version 8.1 Copyright (c) FFmpeg developers\nconfiguration: flags") == "8.1"


def test_published_pattern_strings_are_unchanged():
    record = RecordBase.model_json_schema()["properties"]
    source = SourceAsset.model_json_schema()["properties"]
    assert source["sha256"]["pattern"] == SHA256_PATTERN == r"^sha256:[0-9a-f]{64}$"
    assert record["record_kind"]["pattern"] == RECORD_KIND_PATTERN == r"^[a-z][a-z0-9_]{0,63}$"
    assert record["created_by"]["pattern"] == CREATED_BY_PATTERN == r"^(human|agent|tool)(:[a-z0-9][a-z0-9_.-]{0,63})?$"


@pytest.mark.parametrize("renderer", [CloneRenderer, BlendRenderer])
@pytest.mark.parametrize("path", ["voice.wav", "exports/voice-1.wav"])
def test_valid_export_paths_reach_authorization(renderer, path):
    class ReachedAuthorization(Exception):
        pass

    def reached(**kwargs):
        raise ReachedAuthorization

    sentinel = SimpleNamespace(_authorize_export=reached, _authorize=reached)
    with pytest.raises(ReachedAuthorization):
        renderer.export(
            sentinel,
            output_path=path,
            output_dir="unused",
            line=None,
            profile=None,
            ledger=None,
            context=None,
            at_iso="2026-01-01T00:00:00Z",
        )


@pytest.mark.parametrize(
    "layered,stereo,request_hash,archive_hash",
    [
        (
            False,
            False,
            "3c112105629a2eef8f332e328c8cec643857e092727ba327542d5c660856b954",
            "763945f2bd960fd0c27f65ba8eb4c405bb98a8c214f68b5b0269e987c983b8fa",
        ),
        (
            False,
            True,
            "4b1efdd7b9d13c6fe0fd8474fb56bf270e8966d155e9bcc2b8af66c0cf9618ae",
            "ffadb495b7f315175f5a45ea1498ffa3141f5088db695bbaff57dc9f428ba3d4",
        ),
        (
            True,
            False,
            "ea37195b9811807e54ede956c2e2093e8d2688dac7787d39a70f8320c70797bb",
            "57ff7879964e9cfaa518be52c5a56428924ea38ee981ddd731546d2fef5a989c",
        ),
        (
            True,
            True,
            "dadd4177b461ce446d7a702c5d063cec20c62b78408e0ef29549b263d597aac1",
            "d79637956bdf1c2ba1068913a0282164143d6d5fe82b0c6d9aad191cc1872d9b",
        ),
    ],
)
def test_valid_v4_copy_archives_remain_exact(routed_project, layered, stereo, request_hash, archive_hash):  # noqa: F811
    root, request = (converted_layers if layered else converted_project).__wrapped__(routed_project)
    request["plan"]["format"]["sample_rate_hz"] = 22050
    if stereo:
        make_stereo(root, request)
        if layered:
            data = pcm_to_wav(array("h", [10000, -5000] * 2205), sample_rate_hz=22050, channel_count=2)
            (root / "layer.wav").write_bytes(data)
            request["layer_assets"][0]["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert load_mix_request(request).canonical_id() == "sha256:" + request_hash
    result = _render(root, request)
    assert result["converted_source_count"] == 0 and result["output_sha256"] == "sha256:" + archive_hash
