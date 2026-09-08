"""Failed or truncated rendering must never publish an accepted master."""

import json
import os
from pathlib import Path

import pytest

from kinocut_sound._errors import SoundContractError
from kinocut_sound.public import master_job
from kinocut_sound.public.master_render import parse_normalization
from kinocut_sound.public.master_request import MasterError, load_master_request
from tests.test_sound_master_public import master_project  # noqa: F401 - shared fixture


@pytest.mark.parametrize("kind", ["malformed", "symlink", "fifo", "oversized"])
def test_invalid_backend_output_never_publishes(master_project, monkeypatch, kind):  # noqa: F811
    root, request = master_project
    original = master_job.run_sync

    def corrupt(args, deadline):
        response = original(args, deadline)
        if args[-1].endswith("/master.wav"):
            output = Path(args[-1])
            output.unlink()
            if kind == "malformed":
                output.write_bytes(b"not audio")
            elif kind == "symlink":
                output.symlink_to(root / "source.wav")
            elif kind == "fifo":
                os.mkfifo(output)
            else:
                output.write_bytes(b"0" * (int(args[args.index("-fs") + 1]) + 1))
        return response

    monkeypatch.setattr(master_job, "run_sync", corrupt)
    with pytest.raises(SoundContractError):
        master_job.render_master_request(request, str(root))
    assert not (root / "master.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("missing_summary", [False, True])
def test_actual_successful_size_limit_truncation_is_rejected(master_project, monkeypatch, missing_summary):  # noqa: F811
    root, request = master_project
    original = master_job.render_args

    def limited(job, measurements):
        args = original(job, measurements)
        args[args.index("-fs") + 1] = "8192"
        return args

    monkeypatch.setattr(master_job, "render_args", limited)
    run = master_job.run_sync

    def rendered(args, deadline):
        result = run(args, deadline)
        return b"" if missing_summary and "-fs" in args else result

    monkeypatch.setattr(master_job, "run_sync", rendered)
    with pytest.raises(MasterError) as failure:
        master_job.render_master_request(request, str(root))
    assert failure.value.code == "master_invalid_output"
    assert not (root / "master.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_changed_source_and_deadline_fail_before_launch(master_project, monkeypatch):  # noqa: F811
    root, request = master_project
    monkeypatch.setattr(master_job, "run_sync", lambda *_: pytest.fail("backend must not start"))
    changed = {**request, "source": {**request["source"], "sha256": "sha256:" + "0" * 64}}
    with pytest.raises(SoundContractError):
        master_job.render_master_request(changed, str(root))
    monkeypatch.setattr(master_job, "DEFAULT_MASTER_TOTAL_TIMEOUT_SECONDS", -1)
    with pytest.raises(MasterError) as failure:
        master_job.render_master_request(request, str(root))
    assert failure.value.code == "master_timeout"
    assert not (root / "master.zip").exists()


@pytest.mark.parametrize(
    "field,value",
    [("input_i", "NaN"), ("output_tp", "inf"), ("input_lra", -1), ("normalization_type", "fake"), ("input_tp", True)],
)
def test_invalid_normalizer_summary(field, value):
    summary = {
        name: "0"
        for name in (
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "target_offset",
            "output_i",
            "output_tp",
            "output_lra",
            "output_thresh",
        )
    }
    summary["normalization_type"] = "linear"
    summary[field] = value
    with pytest.raises(MasterError):
        parse_normalization(json.dumps(summary).encode())


def test_mutated_request_model_revalidated(master_project):  # noqa: F811
    root, payload = master_project
    request = load_master_request(payload, str(root))
    request = request.model_copy(update={"output_sample_rate_hz": True})
    with pytest.raises(SoundContractError):
        master_job.render_master_request(request, str(root))
