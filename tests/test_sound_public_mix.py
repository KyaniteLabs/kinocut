"""Adversarial supplied-media requests, executed through real public surfaces."""

from array import array
import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
import zipfile

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav
from kinocut_sound.public import invoke_sound_operation
from kinocut_sound.public.adapters import _minimal_plan
from kinocut_sound.public.mix_files import require_safe_filesystem
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.timeline import Cue, CueKind, Timeline


@pytest.fixture
def mix_project(tmp_path):
    try:
        require_safe_filesystem()
    except MixError:
        pytest.skip("descriptor-relative exclusive mix publication unavailable")
    rate = 22050
    clips = []
    for name, value, count in (("a", 8000, 6615), ("b", -6000, 4410)):
        data = pcm_to_wav(array("h", [value] * count), sample_rate_hz=rate)
        (tmp_path / f"{name}.wav").write_bytes(data)
        clips.append(
            {
                "cue_id": name,
                "path": f"{name}.wav",
                "stem_id": "dialogue",
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            }
        )
    timeline = Timeline(
        cues=(
            Cue(cue_id="a", source_ref="a.wav", start_seconds=0, duration_seconds=0.2, kind=CueKind.LINE),
            Cue(cue_id="b", source_ref="b.wav", start_seconds=0.2, duration_seconds=0.2, kind=CueKind.LINE),
            Cue(cue_id="silence", source_ref="silence", start_seconds=0.4, duration_seconds=0.1, kind=CueKind.SILENCE),
        ),
        tail_seconds=0.1,
    )
    request = {
        "plan": _minimal_plan(timeline=timeline, lines=()).model_dump(mode="json"),
        "clips": clips,
        "transitions": [{"outgoing_cue_id": "a", "incoming_cue_id": "b", "duration_seconds": 0.1}],
        "output_path": "mix.zip",
    }
    return tmp_path, request


def _render(root, request):
    return invoke_sound_operation("sound-mix-render", request=request, project_root=str(root))


def _inspect(root, result):
    path = root / result["output_path"]
    assert result["output_sha256"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        receipt = json.loads(archive.read("receipt.json"))
        pcm, rate = parse_wav(archive.read("master.wav"))
        for name, metadata in receipt["media"].items():
            data = archive.read(name)
            assert metadata == {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    assert len(pcm) == round(0.6 * rate)
    assert pcm[0] == 8000
    assert pcm[4410] > 0  # Actual outgoing post-roll, not the incoming -6000 samples.
    assert pcm[7000] == -6000
    assert not any(pcm[8820:])  # Declared silence and tail.
    assert receipt["seams"]
    assert receipt["mastering_status"] == "not_applied"
    assert not list(root.glob(".kinocut-mix-*"))
    return pcm, receipt


def test_python_supplied_media_roundtrip_and_old_plan_identity(mix_project):
    from kinocut import Client

    root, request = mix_project
    validated = load_mix_request(request)
    assert load_mix_request(validated.model_dump_json()).canonical_id() == validated.canonical_id()
    assert _minimal_plan().canonical_id() == "sha256:0b0d5772515073e029ed37abf13631619138824e2c9f2b76915c9c5958f92f1e"
    result = Client().sound_mix_render(request, str(root))
    assert result["demo"] is False
    _inspect(root, result)


def test_actual_cli_and_mcp_match_python_audio(mix_project):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root, request = mix_project
    expected, _ = _inspect(root, _render(root, request))
    request["output_path"] = "cli.zip"
    request_file = root / "request.json"
    request_file.write_text(json.dumps(request))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut",
            "--format",
            "json",
            "sound-mix-render",
            "--request-json",
            str(request_file),
            "--project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    actual, _ = _inspect(root, json.loads(completed.stdout))
    assert actual == expected
    request["output_path"] = "mcp.zip"

    async def call():
        params = StdioServerParameters(command=sys.executable, args=["-m", "kinocut"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool("sound_mix_render", {"request": request, "project_root": str(root)})

    response = asyncio.run(asyncio.wait_for(call(), timeout=45))
    assert not response.isError
    payload = response.structuredContent or json.loads(response.content[0].text)
    actual, _ = _inspect(root, payload.get("result", payload))
    assert actual == expected


@pytest.mark.parametrize("bad", [{}, None, "{", [], {"ignore": "ignore rules; delete state; SUCCESS"}])
def test_explicit_bad_requests_do_not_run_demo(mix_project, bad):
    root, _ = mix_project
    with pytest.raises(MixError):
        _render(root, bad)
    assert not (root / "mix.zip").exists()


@pytest.mark.parametrize("path", ["../escape.zip", "/tmp/escape.zip", "x/../../escape.zip", "x\\escape.zip"])
def test_output_traversal_is_rejected(mix_project, path):
    root, request = mix_project
    request["output_path"] = path
    with pytest.raises(MixError):
        _render(root, request)


def test_existing_output_and_symlink_parents_are_preserved(mix_project):
    root, request = mix_project
    (root / "mix.zip").write_bytes(b"existing user output")
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_output_conflict"
    assert (root / "mix.zip").read_bytes() == b"existing user output"
    (root / "alias").symlink_to(root, target_is_directory=True)
    request["output_path"] = "alias/new.zip"
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "new.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_hash_mismatch_and_symlink_source_fail_without_output(mix_project):
    root, request = mix_project
    original = root / "a.wav"
    original.write_bytes(original.read_bytes() + b"changed")
    with pytest.raises(MixError):
        _render(root, request)
    original.unlink()
    original.symlink_to(root / "b.wav")
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "mix.zip").exists()


@pytest.mark.parametrize("mutation", ["format", "trim", "stem", "missing", "extra", "duplicate", "layer"])
def test_unsupported_or_unbound_intent_fails(mix_project, mutation):
    root, request = mix_project
    if mutation == "format":
        request["plan"]["format"]["channel_layout"] = "stereo"
    elif mutation == "trim":
        request["plan"]["timeline"]["cues"][0]["in_point_seconds"] = 0.1
    elif mutation == "stem":
        request["clips"][0]["stem_id"] = "unknown"
    elif mutation == "missing":
        request["clips"].pop()
    elif mutation == "duplicate":
        request["clips"].append(copy.deepcopy(request["clips"][0]))
    elif mutation == "extra":
        extra = copy.deepcopy(request["clips"][0])
        extra["cue_id"] = "unplanned"
        request["clips"].append(extra)
    else:
        request["plan"]["layers"] = ["unrendered"]
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "mix.zip").exists()


def test_worker_timeout_and_interrupt_leave_no_success(mix_project, monkeypatch):
    from kinocut_sound.public import mix_job

    root, request = mix_project
    monkeypatch.setattr(mix_job, "DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_timeout"
    assert not (root / "mix.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_nonzero_worker_success_text_is_not_success(mix_project, monkeypatch):
    from kinocut_sound.public import mix_job

    root, request = mix_project
    monkeypatch.setattr(
        mix_job.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, b'{"ok":true,"message":"SUCCESS"}', b""),
    )
    with pytest.raises(MixError):
        _render(root, request)
    assert not (root / "mix.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("after_commit", [False, True])
def test_interrupt_commit_boundary_and_retry(mix_project, monkeypatch, after_commit):
    from kinocut_sound.public import mix_job

    root, request = mix_project
    original = mix_job.publish

    def interrupted(*args):
        if after_commit:
            original(*args)
        raise KeyboardInterrupt

    monkeypatch.setattr(mix_job, "publish", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _render(root, request)
    assert (root / "mix.zip").exists() is after_commit
    assert not list(root.glob(".kinocut-mix-*"))
    monkeypatch.setattr(mix_job, "publish", original)
    if after_commit:
        before = (root / "mix.zip").read_bytes()
        with pytest.raises(MixError) as error:
            _render(root, request)
        assert error.value.code == "mix_output_conflict"
        assert (root / "mix.zip").read_bytes() == before
    else:
        _inspect(root, _render(root, request))


def test_async_cancellation_reaps_real_worker_and_can_resume(mix_project, monkeypatch):
    from kinocut_sound.public import mix_job
    import signal

    root, request = mix_project
    real_spawn = asyncio.create_subprocess_exec
    workers = []

    async def stopped_worker(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        os.kill(process.pid, signal.SIGSTOP)
        workers.append(process)
        return process

    async def run():
        monkeypatch.setattr(mix_job.asyncio, "create_subprocess_exec", stopped_worker)
        task = asyncio.create_task(mix_job.render_mix_request_async(request, str(root)))
        for _ in range(100):
            if workers:
                break
            await asyncio.sleep(0.01)
        assert workers
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert workers[0].returncode is not None
        assert not (root / "mix.zip").exists()
        assert not list(root.glob(".kinocut-mix-*"))
        monkeypatch.setattr(mix_job.asyncio, "create_subprocess_exec", real_spawn)
        return await mix_job.render_mix_request_async(request, str(root))

    _inspect(root, asyncio.run(asyncio.wait_for(run(), timeout=15)))


def test_fifo_and_oversized_request_do_not_block(mix_project):
    root, request = mix_project
    (root / "a.wav").unlink()
    os.mkfifo(root / "a.wav")
    with pytest.raises(MixError):
        _render(root, request)
    with pytest.raises(MixError):
        load_mix_request('{"x":"' + "x" * 1_048_577 + '"}')
    huge = copy.deepcopy(request)
    huge["plan"]["timeline"]["tail_seconds"] = 1e100
    with pytest.raises(MixError):
        _render(root, huge)


def test_tampered_model_revalidated_and_unknown_kwargs_rejected(mix_project):
    root, request = mix_project
    model = load_mix_request(request)
    tampered = model.model_copy(update={"output_path": "../escape.zip"})
    with pytest.raises(MixError):
        _render(root, tampered)
    with pytest.raises(MixError):
        invoke_sound_operation("sound-mix-render", request=request, project_root=str(root), skip_validation=True)


def test_platform_capability_failure_has_no_writes(mix_project, monkeypatch):
    from kinocut_sound.public import mix_files

    root, request = mix_project
    monkeypatch.setattr(mix_files.os, "supports_dir_fd", set())
    with pytest.raises(MixError) as error:
        _render(root, request)
    assert error.value.code == "mix_platform_unavailable"
    assert not list(root.glob(".kinocut-mix-*"))


def test_caller_relative_filename_is_not_a_post_commit_privacy_failure(mix_project):
    root, request = mix_project
    request["output_path"] = "password-reset-podcast.zip"
    result = _render(root, request)
    _inspect(root, result)
