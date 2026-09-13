"""Bad backends, forged worker receipts and cleanup failures cannot publish."""

import asyncio
from contextlib import contextmanager
import sys
import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import mix_conversion_backend, mix_conversion_job, mix_conversion_prepare
from kinocut_sound.public.mix_job import render_mix_request_async
from tests.test_sound_public_mix import mix_project, _render  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project  # noqa: F401


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "script",
    [
        "import sys; sys.stdout.buffer.write(b'\\0'*3)",
        "import sys; sys.stdout.buffer.write(b'\\0'*10)",
        "import os\nwhile True: os.write(1,b'x'*16384)",
        "raise SystemExit(7)",
    ],
)
def test_bad_converter_never_publishes(converted_project, monkeypatch, asynchronous, script):  # noqa: F811
    root, request = converted_project
    monkeypatch.setattr(mix_conversion_backend, "_conversion_args", lambda *args: [sys.executable, "-c", script])
    with pytest.raises(MixError) as error:
        if asynchronous:
            asyncio.run(render_mix_request_async(request, str(root)))
        else:
            _render(root, request)
    assert error.value.code == "mix_conversion_failed"
    assert not (root / "mix.zip").exists() and not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("asynchronous", [False, True])
def test_result_failure_precedes_publication(converted_project, monkeypatch, asynchronous):  # noqa: F811
    root, request = converted_project

    def fail(*args):
        raise TypeError("bad metadata")

    monkeypatch.setattr(mix_conversion_job, "_result", fail)
    with pytest.raises(MixError):
        if asynchronous:
            asyncio.run(render_mix_request_async(request, str(root)))
        else:
            _render(root, request)
    assert not (root / "mix.zip").exists() and not list(root.glob(".kinocut-mix-*"))


def test_private_cleanup_failure_precedes_publication(converted_project, monkeypatch):  # noqa: F811
    root, request = converted_project
    original = mix_conversion_prepare.TemporaryDirectory

    @contextmanager
    def failed_cleanup(*args, **kwargs):
        with original(*args, **kwargs) as directory:
            yield directory
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(mix_conversion_prepare, "TemporaryDirectory", failed_cleanup)
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "mix.zip").exists() and not list(root.glob(".kinocut-mix-*"))


TAMPER_WORKER = """
import json, os, zipfile
from kinocut_sound.public import mix_worker
original = mix_worker._write_bundle
def tamper(fd, *args, **kwargs):
    result = original(fd, *args, **kwargs)
    with os.fdopen(os.dup(fd), 'rb') as handle:
        handle.seek(0)
        with zipfile.ZipFile(handle) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
    receipt = json.loads(members['receipt.json'])
    field = __FIELD__
    if field == 'window':
        receipt['source_windows'][0]['in_sample'] += 1
    elif field == 'original':
        receipt['sources'][0]['path'] = 'forged.wav'
    else:
        receipt['source_resampling']['entries'][0]['raw_frames'] += 1
    members['receipt.json'] = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()
    with os.fdopen(os.dup(fd), 'wb') as handle:
        handle.seek(0)
        handle.truncate()
        with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(members.items()):
                archive.writestr(zipfile.ZipInfo(name), data)
    return result
mix_worker._write_bundle = tamper
raise SystemExit(mix_worker.main())
"""


@pytest.mark.parametrize("field", ["window", "original", "conversion"])
def test_parent_rejects_physically_forged_archive(converted_project, monkeypatch, field):  # noqa: F811
    root, request = converted_project
    original = mix_conversion_job._prepared_worker_args

    def forged(*args):
        argv, descriptors = original(*args)
        script = TAMPER_WORKER.replace("__FIELD__", repr(field))
        return [sys.executable, "-c", script, *argv[3:]], descriptors

    monkeypatch.setattr(mix_conversion_job, "_prepared_worker_args", forged)
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_worker_failed"
    assert not (root / "mix.zip").exists() and not list(root.glob(".kinocut-mix-*"))
