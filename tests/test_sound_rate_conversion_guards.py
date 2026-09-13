"""V4 admission fails before media jobs and publication."""

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import mix_conversion_prepare, mix_conversion_shape, mix_conversion_manifest
from kinocut_sound.public.mix_request import load_mix_request
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project  # noqa: F401


@pytest.mark.parametrize("change", ["profile", "unknown", "dither", "downmix", "version"])
def test_bad_intent_precedes_reads(converted_project, monkeypatch, change):  # noqa: F811
    root, request = converted_project
    if change == "profile":
        request["source_resampling"]["profile"] = "linear_interpolation"
    elif change == "unknown":
        request["source_resampling"]["fallback"] = True
    elif change == "dither":
        request["plan"]["format"]["dither"] = "triangular"
    elif change == "downmix":
        request["plan"]["format"]["conversion"]["allowed_downmix_presets"] = ["itu_stereo"]
    else:
        request["schema_version"] = True

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid intent read a source")

    monkeypatch.setattr(mix_conversion_prepare, "read_asset", forbidden)
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "mix.zip").exists()


@pytest.mark.parametrize("kind,limit", [("work", 158102), ("derived", 32087), ("manifest", 1)])
def test_resource_admission_precedes_conversion(converted_project, monkeypatch, kind, limit):  # noqa: F811
    root, request = converted_project

    def forbidden(*args, **kwargs):
        raise AssertionError("over-limit request started a media conversion")

    monkeypatch.setattr(mix_conversion_prepare, "_convert_sync", forbidden)
    if kind == "work":
        monkeypatch.setattr(mix_conversion_shape, "MAX_MIX_CONVERSION_WORK_UNITS", limit)
    elif kind == "derived":
        monkeypatch.setattr(mix_conversion_shape, "MAX_MIX_CONVERTED_BYTES", limit)
    else:
        monkeypatch.setattr(mix_conversion_manifest, "MAX_MIX_CONVERSION_MANIFEST_BYTES", limit)
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_over_limit"
    assert not (root / "mix.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_exact_work_and_derived_limits_are_allowed(converted_project, monkeypatch):  # noqa: F811
    root, request = converted_project
    monkeypatch.setattr(mix_conversion_shape, "MAX_MIX_CONVERSION_WORK_UNITS", 158103)
    monkeypatch.setattr(mix_conversion_shape, "MAX_MIX_CONVERTED_BYTES", 32088)
    assert _render(root, request)["converted_source_count"] == 2


def test_typed_corruption_is_revalidated(converted_project):  # noqa: F811
    _root, payload = converted_project
    request = load_mix_request(payload)
    broken = request.model_copy(update={"schema_version": True})
    with pytest.raises(MixError):
        load_mix_request(broken)
