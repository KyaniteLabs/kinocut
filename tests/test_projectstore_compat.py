"""Compact compat-bridge behavior tests + one real Phase-1 exit E2E.

Exercises :mod:`kinocut.projectstore.compat` fail-closed, then one end-to-end Phase-1
exit (CAS ingest, compile, synthesis, submit, SIGKILL, reopen/resume, lineage receipt).
"""

from __future__ import annotations

import json
import os
import time

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    CAS_PRODUCER_KINDS,
    CLOSED_KINDS,
    WorkflowSpecSynthesis,
    compile_operations,
    compile_repurpose_slice,
    create_edit_project,
    event_poll,
    get_edit_project,
    ingest_blob,
    materialize_workflow_sources,
    open_project,
    resolve_blob,
    start_render_job,
    submit_render_job,
    synthesize_workflow_spec,
)
from kinocut.projectstore import render_jobs
from kinocut.workflow import validate_workflow_spec

_D = "sha256:" + "a" * 64
_D2 = "sha256:" + "b" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "proj")


def _cas(project, data: bytes = b"x", *, media_type: str | None = "video/mp4") -> str:
    """Ingest deterministic bytes into CAS and return the digest (default video/mp4)."""
    src = project.root / f"_src_{abs(hash((data, media_type))) & 0xFFFFFFFF:08x}"
    src.write_bytes(data)
    return ingest_blob(project, src, media_type=media_type).digest


def _project_files(root):
    """Relative paths of every file under ``root`` for the fail-closed 'created no files' check."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def _raise(fn, *args, **kw):
    with pytest.raises(MCPVideoError):
        fn(*args, **kw)


def test_operation_ids_deterministic_order_bound_param_invariant():
    t1 = {"kind": "trim", "source": _D, "start": 0.0, "end": 1.0}
    t2 = {"kind": "trim", "source": _D2, "start": 0.0, "end": 1.0}
    ids = compile_operations([t1])
    assert ids == compile_operations([t1])  # deterministic
    assert all(i.startswith("sha256:") and len(i) == 71 for i in ids)
    assert compile_operations([t1, t2]) != compile_operations([t2, t1])  # order-bound
    assert compile_operations([{"kind": "trim", "source": _D, "start": 0.0, "end": 2.0}]) != ids
    # input dict key order is irrelevant (canonical normalisation + sort_keys)
    assert compile_operations([{"end": 1.0, "kind": "trim", "source": _D, "start": 0.0}]) == ids


def test_closed_kinds_accepted_cas_producers_and_unknown_rejected():
    valid = {
        "trim": {"kind": "trim", "source": _D, "start": 0.0, "end": 1.0},
        "merge": {"kind": "merge", "sources": [_D, _D2]},
        "burn_in": {"kind": "burn_in", "source": _D, "subtitle": _D2},
        "reframe": {"kind": "reframe", "source": _D, "width": 128, "height": 96},
        "crop": {"kind": "crop", "source": _D, "x": 0, "y": 0, "width": 100, "height": 100},
        "silence_cut": {"kind": "silence_cut", "source": _D, "keep_segments": [[0.0, 1.0], [2.0, 3.0]]},
    }
    for kind in CLOSED_KINDS:
        assert len(compile_operations([valid[kind]])) == 1  # every closed kind compiles
    for kind in CAS_PRODUCER_KINDS:
        _raise(compile_operations, [{"kind": kind}])  # CAS producers never compiled
    _raise(compile_operations, [{"kind": "bogus"}])  # unknown kind
    _raise(compile_operations, [{"kind": "trim", "source": _D, "start": 0.0, "end": 1.0, "extra": 1}])
    _raise(compile_operations, [{"kind": "merge", "sources": [_D]}])  # < 2 sources
    _raise(compile_operations, [{"kind": "trim", "source": "not-a-digest", "start": 0, "end": 1}])


def test_param_validation_rejects_nonfinite_bad_types_and_bad_ranges():
    nan = float("nan")
    inf = float("inf")
    # trim: start/end must be nonneg finite, end > start
    for bad in [nan, inf, -1.0, True, "x"]:
        _raise(compile_operations, [{"kind": "trim", "source": _D, "start": bad, "end": 1.0}])
    _raise(compile_operations, [{"kind": "trim", "source": _D, "start": 2.0, "end": 1.0}])  # end <= start
    # reframe: width/height must be int >= 1
    for bad in [0, -1, 1.5, True, "x"]:
        _raise(compile_operations, [{"kind": "reframe", "source": _D, "width": bad, "height": 96}])
    # crop: x/y int >= 0, w/h int >= 1
    _raise(compile_operations, [{"kind": "crop", "source": _D, "x": -1, "y": 0, "width": 1, "height": 1}])
    _raise(compile_operations, [{"kind": "crop", "source": _D, "x": 0, "y": 0, "width": 0, "height": 1}])
    # silence_cut: ordered non-overlapping segments
    _raise(compile_operations, [{"kind": "silence_cut", "source": _D, "keep_segments": []}])
    _raise(compile_operations, [{"kind": "silence_cut", "source": _D, "keep_segments": [[1.0, 0.0]]}])
    _raise(compile_operations, [{"kind": "silence_cut", "source": _D, "keep_segments": [[0.0, 2.0], [1.0, 3.0]]}])


def test_compile_repurpose_slice_append_stale_base_revision_event(project):
    ep = create_edit_project(project)
    ops = [{"kind": "trim", "source": _D, "start": 0.0, "end": 1.0}]
    r1 = compile_repurpose_slice(project, ep.edit_project_id, ops)  # base=None for first revision
    assert r1.revision_number == 1 and r1.parent_revision_id is None
    head1 = get_edit_project(project, ep.edit_project_id)
    assert head1.head_revision_id == r1.record_id
    # stale base rejected
    _raise(compile_repurpose_slice, project, ep.edit_project_id, ops, base_revision_id=None)
    # correct base advances head by exactly one
    r2 = compile_repurpose_slice(project, ep.edit_project_id, ops, base_revision_id=r1.record_id)
    assert r2.revision_number == 2 and r2.parent_revision_id == r1.record_id
    assert get_edit_project(project, ep.edit_project_id).head_revision_id == r2.record_id
    # revision.created event emitted for each append
    events = event_poll(project, event_kinds=("revision.created",))
    assert len(events) == 2
    assert [e.event_id for e in events] == [1, 2]
    assert [e.revision_id for e in events] == [r1.record_id, r2.record_id]


def test_synthesis_lowering_and_validator_acceptance(project):
    d1, d2 = _cas(project, b"a"), _cas(project, b"b")
    ep = create_edit_project(project)
    ops = [
        {"kind": "trim", "source": d1, "start": 0.0, "end": 1.0},
        {"kind": "merge", "sources": [d1, d2]},
        {"kind": "reframe", "source": d1, "width": 128, "height": 96},
        {"kind": "silence_cut", "source": d1, "keep_segments": [[0.0, 1.0], [2.0, 3.0]]},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops)
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops, base_revision_id=rev.record_id)
    spec = syn.spec
    assert spec["schema_version"] == 1 and spec["name"] == "repurpose_slice"
    step_ops = [s["op"] for s in spec["steps"]]
    # trim→trim, merge→merge, reframe→resize, silence_cut→trim+trim+merge
    assert step_ops == ["trim", "merge", "resize", "trim", "trim", "merge"]
    assert syn.unrendered_kinds == ()  # all renderable
    # silence_cut merge reads @work intermediates from the two trims
    sc_merge = spec["steps"][-1]
    assert all(s.startswith("@work/") for s in sc_merge["inputs"]["srcs"])
    # generated spec passes the shipped validator
    sp = project.root / "spec.json"
    sp.write_text(json.dumps(spec))
    verdict = validate_workflow_spec(str(sp))
    assert verdict["valid"] is True
    assert set(verdict["ops"]) == {"trim", "merge", "resize"}


def test_burn_in_and_crop_lowered_to_agreed_workflow_ops(project):
    d1, d2 = _cas(project, b"a"), _cas(project, b"b")
    ep = create_edit_project(project)
    ops = [
        {"kind": "trim", "source": d1, "start": 0.0, "end": 1.0},
        {"kind": "burn_in", "source": d1, "subtitle": d2},
        {"kind": "crop", "source": d1, "x": 0, "y": 0, "width": 10, "height": 10},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops)
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops, base_revision_id=rev.record_id)
    # crop and burn_in are now renderable: nothing is reported unrendered, all three lower.
    assert syn.unrendered_kinds == ()
    assert [s["op"] for s in syn.spec["steps"]] == ["trim", "burn_in", "crop"]
    digest_to_id = {digest: sid for sid, digest in syn.source_digests.items()}
    burn_step = next(s for s in syn.spec["steps"] if s["op"] == "burn_in")
    # burn_in lowers video + subtitle as an ordered multi-source input over the agreed op name.
    assert list(burn_step["inputs"]["srcs"]) == [
        "@sources." + digest_to_id[d1],
        "@sources." + digest_to_id[d2],
    ]
    assert burn_step["params"] == {}
    crop_step = next(s for s in syn.spec["steps"] if s["op"] == "crop")
    assert crop_step["inputs"] == {"src": "@sources." + digest_to_id[d1]}
    assert crop_step["params"] == {"x": 0, "y": 0, "width": 10, "height": 10}


def test_synthesis_rejects_operations_not_matching_revision(project):
    """Trusted binding: lowering may not claim a revision the operations did not build."""
    d1, d2 = _cas(project, b"a"), _cas(project, b"b")
    ep = create_edit_project(project)
    ops_a = [
        {"kind": "trim", "source": d1, "start": 0.0, "end": 1.0},
        {"kind": "reframe", "source": d2, "width": 128, "height": 96},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops_a)
    files_before = _project_files(project.root)

    # different operations (param change) claiming the same revision -> fail closed
    ops_b = [
        {"kind": "trim", "source": d1, "start": 0.0, "end": 2.0},
        {"kind": "reframe", "source": d2, "width": 128, "height": 96},
    ]
    _raise(synthesize_workflow_spec, project, ep.edit_project_id, ops_b, base_revision_id=rev.record_id)
    # reordered operations claiming the same revision -> fail closed (order binds into the ids)
    _raise(synthesize_workflow_spec, project, ep.edit_project_id, [ops_a[1], ops_a[0]], base_revision_id=rev.record_id)

    # fail-closed: synthesis is read-only, so no durable files were created and the head is unchanged
    assert _project_files(project.root) == files_before
    assert get_edit_project(project, ep.edit_project_id).head_revision_id == rev.record_id

    # matching operations lower successfully and bind the same revision
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops_a, base_revision_id=rev.record_id)
    assert [s["op"] for s in syn.spec["steps"]] == ["trim", "resize"]
    assert syn.unrendered_kinds == ()


_FAKE_FFPROBE = """\
#!/usr/bin/env python3
import sys
sys.stdout.write(
    '{"streams":[{"codec_type":"video","codec_name":"h264","width":320,"height":240,'
    '"r_frame_rate":"30/1","duration":"2.000000","side_data_list":[]}],'
    '"format":{"duration":"2.000000","bit_rate":"100000","size":"1234",'
    '"format_name":"mov,mp4,m4a,3gp,3g2,mj2"}}'
)
"""

_FAKE_FFMPEG = """\
#!/usr/bin/env python3
import os, sys, time
a = sys.argv[1:]
if "-version" in a:
    sys.stdout.write("ffmpeg version kinocut-fake-1.0.0 (test shim)\\n")
    sys.exit(0)
if "-filters" in a:
    sys.exit(0)
ctr = os.environ.get("KINOCUT_TEST_FFMPEG_COUNTER", "")
tok = os.environ.get("KINOCUT_TEST_FFMPEG_BLOCK_TOKEN", "")
if ctr:
    try:
        n = int(open(ctr).read().strip() or "0")
    except (OSError, ValueError):
        n = 0
    n += 1
    open(ctr, "w").write(str(n))
    if n >= 2 and tok and os.path.exists(tok):
        while True:
            time.sleep(0.2)
out = sys.argv[-1] if len(sys.argv) > 1 else ""
if out and not out.startswith("-"):
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out, "wb") as h:
        h.write(b"kinocut-fake-ffmpeg-output")
sys.exit(0)
"""


def _install_fake_binaries(bin_dir):
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "ffprobe").write_text(_FAKE_FFPROBE)
    (bin_dir / "ffmpeg").write_text(_FAKE_FFMPEG)
    for name in ("ffprobe", "ffmpeg"):
        os.chmod(bin_dir / name, 0o700)
    return bin_dir


def test_phase1_exit_kill_reopen_resume_lineage_and_events(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")

    # --- CAS idempotent ingest (same bytes → same identity) ---
    blob_src = project.root / "media.bin"
    blob_src.write_bytes(b"kinocut-deterministic-input-media")
    m1 = ingest_blob(project, blob_src, media_type="video/mp4")
    m2 = ingest_blob(project, blob_src, media_type="video/mp4")
    assert m1.digest == m2.digest and m1.record_id == m2.record_id  # idempotent identity
    resolve_blob(project, m1.digest)  # integrity-checked CAS blob resolves cleanly

    # --- compile a renderable operation revision ---
    ep = create_edit_project(project)
    ops = [
        {"kind": "trim", "source": m1.digest, "start": 0.0, "end": 1.0},
        {"kind": "trim", "source": m1.digest, "start": 2.0, "end": 3.0},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops)
    assert rev.revision_number == 1

    # --- synthesise / write safe spec and source ---
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops, base_revision_id=rev.record_id)
    assert syn.unrendered_kinds == ()
    assert syn.source_digests == {"src0": m1.digest}  # carried source-id → digest mapping
    assert syn.spec["sources"]["src0"]["path"] == "sources/src0.mp4"  # opaque, no CAS-layout leakage
    spec_path = project.root / "render_spec.json"
    spec_path.write_text(json.dumps(syn.spec))
    assert validate_workflow_spec(str(spec_path))["valid"] is True  # validator acceptance

    # --- submit detached async job ---
    job = submit_render_job(
        project, edit_project_id=ep.edit_project_id, revision_id=rev.record_id, spec_path=str(spec_path)
    )
    # Product helper hard-links each declared CAS source into the frozen job dir (no test-side CAS-layout knowledge).
    materialize_workflow_sources(project, job.job_id, syn)
    linked = render_jobs.job_spec_path(project, job.job_id).parent / "sources" / "src0.mp4"
    assert linked.is_file() and linked.stat().st_nlink >= 2  # hard-linked to CAS blob, not copied
    materialize_workflow_sources(project, job.job_id, syn)  # idempotent: repeat call is a no-op
    linked.unlink()  # detach the materialized hardlink so the CAS inode itself stays intact
    linked.write_bytes(b"corrupt")  # separate corrupt regular file at the declared path (torn prior run)
    assert linked.stat().st_nlink == 1  # regular file, not hard-linked into the CAS blob
    _raise(materialize_workflow_sources, project, job.job_id, syn)  # fail closed, no silent overwrite
    linked.unlink()  # remove the corrupt regular file so the detached runner reads clean bytes
    materialize_workflow_sources(project, job.job_id, syn)  # re-materialize a fresh hard-link

    # --- deterministic fake ffprobe/ffmpeg on the detached child's inherited PATH ---
    block_token = tmp_path / "block-ffmpeg"
    block_token.write_text("1")
    counter_file = tmp_path / "ffmpeg-counter"
    counter_file.write_text("0")
    bin_dir = _install_fake_binaries(tmp_path / "fakebin")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("KINOCUT_TEST_FFMPEG_BLOCK_TOKEN", str(block_token))
    monkeypatch.setenv("KINOCUT_TEST_FFMPEG_COUNTER", str(counter_file))

    receipt_path = render_jobs.job_receipt_path(project, job.job_id)
    running = start_render_job(project, job.job_id)
    assert running.status.value == "running" and running.runner_pid > 1

    # Stage 1 (first trim) completes → executor persists its real progressive receipt.
    deadline = time.monotonic() + 20
    first_receipt = None
    while time.monotonic() < deadline:
        if receipt_path.exists():
            try:
                first_receipt = json.loads(receipt_path.read_text())
            except (OSError, json.JSONDecodeError):
                first_receipt = None
            if (
                first_receipt
                and any(s.get("status") == "completed" for s in first_receipt.get("steps", []))
                and any(s.get("status") == "pending" for s in first_receipt.get("steps", []))
            ):
                break
        time.sleep(0.05)
    else:
        render_jobs.terminate_render_job(project, job.job_id)
        raise AssertionError("stage 1 did not persist a progressive receipt before stage 2")
    assert first_receipt is not None
    first_s1 = first_receipt["steps"][0]
    assert first_s1["status"] == "completed"
    first_input_hash = first_s1["input_hashes"]["src"]

    # --- SIGKILL the real runner during stage 2 ---
    failed = render_jobs.terminate_render_job(project, job.job_id)
    assert failed.status.value == "failed" and failed.error_code == "terminated"

    # --- reopen / resume: prove stage 1 unchanged / skipped ---
    block_token.unlink()  # fake ffmpeg no longer blocks
    counter_file.write_text("0")  # reset counter for the resumed run
    reopened = open_project(project.root)
    resumed = render_jobs.resume_render_job(reopened, job.job_id)
    assert resumed.status.value == "queued"
    restarted = start_render_job(reopened, job.job_id)
    assert restarted.runner_pid != running.runner_pid

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if render_jobs.get_render_job(reopened, job.job_id).status.value == "succeeded":
            break
        time.sleep(0.05)
    else:
        render_jobs.terminate_render_job(reopened, job.job_id)
        raise AssertionError("resumed runner did not succeed")

    final = json.loads(receipt_path.read_text())
    s1, s2 = final["steps"]
    assert s1["status"] == "completed" and s1.get("skipped") is True  # stage 1 skipped on resume
    assert s1["input_hashes"]["src"] == first_input_hash  # identical input → unchanged
    assert s2["status"] == "completed" and s2.get("skipped") is not True  # stage 2 re-ran
    assert final["status"] == "completed"
    assert final["feature_flags"]["resume_used"] is True

    # --- schema-pure receipt: exact lineage fields, no MCP success envelope ---
    assert "success" not in final  # runner strips the envelope-only key
    lineage = final["lineage"]
    assert lineage["edit_project_id"] == ep.edit_project_id
    assert lineage["revision_id"] == rev.record_id
    assert lineage["job_id"] == job.job_id
    assert lineage["source_digests"] == [m1.digest]
    assert lineage["output_digest"].startswith("sha256:")
    assert len(lineage["toolchain_fingerprint"]) > 0

    # --- event_poll sees ordered revision.created then render.completed ---
    events = event_poll(reopened)
    kinds = [e.event_kind for e in events]
    assert "revision.created" in kinds and "render.completed" in kinds
    assert kinds.index("revision.created") < kinds.index("render.completed")
    rev_ev = next(e for e in events if e.event_kind == "revision.created")
    assert rev_ev.revision_id == rev.record_id
    rnd_ev = next(e for e in events if e.event_kind == "render.completed")
    assert rnd_ev.job_id == job.job_id and rnd_ev.revision_id == rev.record_id


def test_materialize_rejects_forged_source_ids_fail_closed(project):
    digest = _cas(project, b"forged")
    ep = create_edit_project(project)
    rev = compile_repurpose_slice(
        project, ep.edit_project_id, [{"kind": "trim", "source": digest, "start": 0.0, "end": 1.0}]
    )
    syn = synthesize_workflow_spec(
        project,
        ep.edit_project_id,
        [{"kind": "trim", "source": digest, "start": 0.0, "end": 1.0}],
        base_revision_id=rev.record_id,
    )
    (project.root / "spec.json").write_text(json.dumps(syn.spec))
    job = submit_render_job(
        project,
        edit_project_id=ep.edit_project_id,
        revision_id=rev.record_id,
        spec_path=str(project.root / "spec.json"),
    )
    job_dir = render_jobs.job_spec_path(project, job.job_id).parent
    # forged traversal/slash/dot/non-closed-form source IDs all fail closed before any link
    for forged in ["../evil", "src0/evil", "evil/../src0", ".", "..", "", "src", "srcx", "SRC0", "src-0"]:
        _raise(
            materialize_workflow_sources,
            project,
            job.job_id,
            WorkflowSpecSynthesis(spec={"sources": {}}, unrendered_kinds=(), source_digests={forged: digest}),
        )
    assert (
        sorted(p.name for p in job_dir.iterdir()) == ["sources", "spec.json"]
        and list((job_dir / "sources").iterdir()) == []
    )


def test_crop_modes_compile_and_reject_mixed_incomplete():
    pix = {"kind": "crop", "source": _D, "width": 100, "height": 80}
    pix_xy = {"kind": "crop", "source": _D, "x": 4, "y": 2, "width": 100, "height": 80}
    pct = {"kind": "crop", "source": _D, "crop_percent": 50}
    assert compile_operations([pix])  # pixel mode compiles
    assert compile_operations([pct])  # percent mode compiles
    assert compile_operations([pix]) != compile_operations([pct])  # distinct modes bind distinct ids
    assert compile_operations([pix]) != compile_operations([pix_xy])  # x/y bind into the id
    # input dict key order is irrelevant (canonical normalization)
    assert compile_operations([pix]) == compile_operations([{"height": 80, "kind": "crop", "source": _D, "width": 100}])
    # crop_percent normalizes int/float to the same id
    assert compile_operations([{"kind": "crop", "source": _D, "crop_percent": 50}]) == compile_operations(
        [{"kind": "crop", "source": _D, "crop_percent": 50.0}]
    )
    # mixed modes / incomplete groups / x-y-without-pixels all fail closed
    _raise(compile_operations, [{"kind": "crop", "source": _D, "width": 1, "height": 1, "crop_percent": 50}])
    _raise(compile_operations, [{"kind": "crop", "source": _D, "width": 1}])  # missing height
    _raise(compile_operations, [{"kind": "crop", "source": _D, "height": 1}])  # missing width
    _raise(compile_operations, [{"kind": "crop", "source": _D}])  # neither mode
    _raise(compile_operations, [{"kind": "crop", "source": _D, "crop_percent": 50, "x": 0}])  # x needs pixels
    _raise(compile_operations, [{"kind": "crop", "source": _D, "crop_percent": 50, "y": 0}])  # y needs pixels
    # crop_percent must be a finite number in (0, 100]
    for bad in [0, 0.0, -1, 100.5, 101, True, "50", None, float("inf"), float("nan")]:
        _raise(compile_operations, [{"kind": "crop", "source": _D, "crop_percent": bad}])


def test_crop_percent_mode_lowered_and_centered_pixel_omits_xy(project):
    d = _cas(project, b"crop-src")
    ep = create_edit_project(project)
    ops = [
        {"kind": "crop", "source": d, "x": 1, "y": 2, "width": 100, "height": 80},
        {"kind": "crop", "source": d, "width": 64, "height": 48},  # centered: x/y omitted
        {"kind": "crop", "source": d, "crop_percent": 25},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops)
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops, base_revision_id=rev.record_id)
    crop_steps = [s for s in syn.spec["steps"] if s["op"] == "crop"]
    assert len(crop_steps) == 3
    assert crop_steps[0]["params"] == {"x": 1, "y": 2, "width": 100, "height": 80}
    assert crop_steps[1]["params"] == {"width": 64, "height": 48}  # no x/y -> engine centers
    assert crop_steps[2]["params"] == {"crop_percent": 25.0}  # percent normalized to float
    for step in crop_steps:
        assert set(step["inputs"]) == {"src"}


def test_source_extensions_derived_from_media_type_and_subtitle_role(project):
    video = _cas(project, b"video", media_type="video/mp4")
    webm = _cas(project, b"webm", media_type="video/webm")
    srt = _cas(project, b"sub-srt", media_type="application/x-subrip")
    vtt = _cas(project, b"sub-vtt", media_type="text/vtt")
    ass = _cas(project, b"sub-ass", media_type="application/x-ass")
    raw_sub = _cas(project, b"raw-sub", media_type=None)  # no media_type -> role fallback
    ep = create_edit_project(project)
    ops = [
        {"kind": "crop", "source": video, "width": 2, "height": 2},
        {"kind": "burn_in", "source": webm, "subtitle": srt},
        {"kind": "burn_in", "source": video, "subtitle": vtt},
        {"kind": "burn_in", "source": webm, "subtitle": ass},
        {"kind": "burn_in", "source": video, "subtitle": raw_sub},
    ]
    rev = compile_repurpose_slice(project, ep.edit_project_id, ops)
    syn = synthesize_workflow_spec(project, ep.edit_project_id, ops, base_revision_id=rev.record_id)
    digest_to_path = {syn.source_digests[sid]: entry["path"] for sid, entry in syn.spec["sources"].items()}
    # CAS media_type is the primary determinant; subtitle tracks keep .srt/.vtt/.ass verbatim.
    assert digest_to_path[video].endswith(".mp4")
    assert digest_to_path[webm].endswith(".webm")
    assert digest_to_path[srt].endswith(".srt")
    assert digest_to_path[vtt].endswith(".vtt")
    assert digest_to_path[ass].endswith(".ass")
    # a media-type-less subtitle source falls back to the subtitle role (.srt)
    assert digest_to_path[raw_sub].endswith(".srt")
    # every declared source path is confined under the opaque sources/ job-relative directory
    for path in digest_to_path.values():
        parts = path.split("/")
        assert parts[0] == "sources" and ".." not in parts and len(parts) == 2


def test_synthesis_spec_is_deterministic_including_extensions(tmp_path):
    """Same inputs lower to the same spec (paths/extensions/steps) across projects."""

    def build(tag):
        project = open_project(tmp_path / f"proj-{tag}")
        video = _cas(project, b"v", media_type="video/webm")
        sub = _cas(project, b"s", media_type="text/vtt")
        ep = create_edit_project(project)
        local_ops = [
            {"kind": "trim", "source": video, "start": 0.0, "end": 1.0},
            {"kind": "burn_in", "source": video, "subtitle": sub},
            {"kind": "crop", "source": video, "crop_percent": 50},
        ]
        rev = compile_repurpose_slice(project, ep.edit_project_id, local_ops)
        return synthesize_workflow_spec(project, ep.edit_project_id, local_ops, base_revision_id=rev.record_id)

    a, b = build("a"), build("b")
    assert a.spec == b.spec  # identical incl. media-type-derived source paths and lowered steps
    assert a.source_digests == b.source_digests


def test_materialize_hardlinks_non_mp4_subtitle_source(project):
    video = _cas(project, b"vid", media_type="video/mp4")
    sub = _cas(project, b"cap", media_type="application/x-subrip")
    ep = create_edit_project(project)
    # a validator-known trim spec creates a real frozen job (and job dir) we can materialize into.
    trim_ops = [{"kind": "trim", "source": video, "start": 0.0, "end": 1.0}]
    rev = compile_repurpose_slice(project, ep.edit_project_id, trim_ops)
    trim_syn = synthesize_workflow_spec(project, ep.edit_project_id, trim_ops, base_revision_id=rev.record_id)
    (project.root / "spec.json").write_text(json.dumps(trim_syn.spec))
    job = submit_render_job(
        project,
        edit_project_id=ep.edit_project_id,
        revision_id=rev.record_id,
        spec_path=str(project.root / "spec.json"),
    )
    # materialize reads declared paths from the passed synthesis (shared source map), so a
    # subtitle-track (.srt) source is hard-linked at its media-type-derived suffix.
    sub_syn = WorkflowSpecSynthesis(
        spec={"sources": {"src0": {"path": "sources/src0.srt"}}},
        unrendered_kinds=(),
        source_digests={"src0": sub},
    )
    materialize_workflow_sources(project, job.job_id, sub_syn)
    job_dir = render_jobs.job_spec_path(project, job.job_id).parent
    linked = job_dir / "sources" / "src0.srt"
    assert linked.is_file() and linked.stat().st_nlink >= 2  # hard-linked into CAS, not copied
    materialize_workflow_sources(project, job.job_id, sub_syn)  # idempotent: repeat is a no-op
    linked.unlink()  # detach the materialized hardlink so the CAS inode itself stays intact
    linked.write_bytes(b"corrupt")  # separate corrupt regular file at the declared .srt path
    assert linked.stat().st_nlink == 1  # regular file, not hard-linked into the CAS blob
    _raise(materialize_workflow_sources, project, job.job_id, sub_syn)  # fail closed, no silent overwrite
