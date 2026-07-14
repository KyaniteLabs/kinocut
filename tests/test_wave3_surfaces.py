"""Public MCP, CLI, and Python parity for Wave 3 governed operations."""

from __future__ import annotations

import inspect
import json
import os
from contextlib import suppress
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.source_identity import immutable_verified_snapshot_available

_MAX_AUTH_IDS, _MAX_JSON_BYTES = 64, 65_536


def _run_cli(monkeypatch, capsys, *args: str) -> tuple[int, dict]:
    from kinocut.__main__ import main

    monkeypatch.setattr("sys.argv", ["kino", "--format", "json", *args])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code)
    stream = capsys.readouterr()
    return code, json.loads(stream.out or stream.err)


def test_all_transports_delegate_to_one_wave3_boundary(monkeypatch, capsys, tmp_path):
    from kinocut.aivideo import wave3_surfaces
    from kinocut.client import Client
    from kinocut.server_tools_aivideo import (
        video_acceptance_eval,
        video_body_swap,
        video_salvage,
        video_verdict,
    )

    calls: list[tuple[str, dict]] = []

    def fake(operation: str, **kwargs):
        calls.append((operation, kwargs))
        return {"success": True, "operation": operation, "arguments": kwargs}

    monkeypatch.setattr(wave3_surfaces, "run_wave3_operation", fake)
    client = Client()
    project = str(tmp_path / "project")
    video = str(tmp_path / "video.mp4")
    audio = str(tmp_path / "audio.wav")
    output = str(tmp_path / "output.mp4")
    digest = "sha256:" + "a" * 64
    verdict = {
        "asset_hash": digest,
        "disposition": "approved",
        "acceptance_spec_id": digest,
        "reviewer": "editor",
        "rationale": "approved after review",
    }
    cases = (
        (
            "verdict",
            lambda: client.verdict(project, verdict),
            lambda: video_verdict(project, verdict),
            ("video-verdict", project, "--verdict-json", json.dumps(verdict)),
        ),
        (
            "acceptance_eval",
            lambda: client.acceptance_eval(project, digest, [digest]),
            lambda: video_acceptance_eval(project, digest, [digest]),
            (
                "video-acceptance-eval",
                project,
                digest,
                "--verdict-id",
                digest,
            ),
        ),
        (
            "body_swap",
            lambda: client.body_swap(
                project,
                video,
                audio,
                output,
                duration_policy="pad_video",
                authorization_decision_ids=[digest],
            ),
            lambda: video_body_swap(
                project,
                video,
                audio,
                output,
                duration_policy="pad_video",
                authorization_decision_ids=[digest],
            ),
            (
                "video-body-swap",
                project,
                video,
                audio,
                output,
                "--duration-policy",
                "pad_video",
                "--authorization-decision-id",
                digest,
            ),
        ),
        (
            "salvage",
            lambda: client.salvage(
                project,
                digest,
                "still_frame",
                {"timestamp": 0.5},
                digest,
                authorization_decision_ids=[digest],
            ),
            lambda: video_salvage(
                project,
                digest,
                "still_frame",
                {"timestamp": 0.5},
                digest,
                authorization_decision_ids=[digest],
            ),
            (
                "video-salvage",
                project,
                digest,
                "still_frame",
                digest,
                "--policy-json",
                json.dumps({"timestamp": 0.5}),
                "--authorization-decision-id",
                digest,
            ),
        ),
    )
    for operation, python_call, mcp_call, cli_args in cases:
        expected = python_call()
        assert mcp_call() == expected
        code, cli_result = _run_cli(monkeypatch, capsys, *cli_args)
        assert code == 0
        assert cli_result == expected
        assert [name for name, _ in calls[-3:]] == [operation] * 3


def test_wave3_public_signatures_offer_no_bypass_parameter():
    from kinocut.client import Client
    from kinocut.server_tools_aivideo import (
        video_acceptance_eval,
        video_body_swap,
        video_salvage,
        video_verdict,
    )

    callables = (
        Client.verdict,
        Client.acceptance_eval,
        Client.body_swap,
        Client.salvage,
        video_verdict,
        video_acceptance_eval,
        video_body_swap,
        video_salvage,
    )
    for function in callables:
        parameters = inspect.signature(function).parameters
        assert not ({"force", "override", "bypass"} & parameters.keys())


def test_wave3_commands_are_registered():
    from kinocut.cli.parser import build_parser

    parser = build_parser()
    digest = "sha256:" + "a" * 64
    commands = (
        ("video-verdict", "project", "--verdict-json", "{}"),
        (
            "video-acceptance-eval",
            "project",
            digest,
            "--verdict-id",
            digest,
        ),
        ("video-body-swap", "project", "video", "audio", "output"),
        (
            "video-salvage",
            "project",
            digest,
            "still_frame",
            digest,
            "--policy-json",
            "{}",
        ),
    )
    for arguments in commands:
        assert parser.parse_args(arguments).command == arguments[0]


def _governed_project(tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.verdict import acceptance_dependency_fingerprint
    from kinocut.contracts.acceptance import acceptance_requirement_ids
    from kinocut.contracts.acceptance import GenerationAcceptanceSpec
    from kinocut.contracts.review import ReviewDecision
    from kinocut.contracts.verdict import ClipVerdict
    from kinocut.projectstore import append_record, ingest_asset, open_project
    from kinocut.projectstore.artifacts import install_bytes
    from tests.contracts_fixtures import (
        acceptance_spec_kwargs,
        review_decision_kwargs,
        verdict_kwargs,
    )

    project = open_project(tmp_path / "project")
    project_id = project.project_id
    video = ingest_asset(project, sample_video)
    audio = ingest_asset(project, sample_audio)
    spec = append_record(
        project,
        GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project_id)),
    )
    evidence = install_bytes(project, b"wave3 motion-strip evidence", name="motion-strip.png")
    decision = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project_id,
                created_by="human:editor",
                target_ref=video.asset_id,
                acceptance_spec_id=spec.record_id,
                review_role="editor",
                evidence_artifacts=(
                    {
                        "requirement_id": "motion_strip",
                        "artifact_id": evidence.artifact_id,
                    },
                ),
                covered_requirement_ids=acceptance_requirement_ids(spec),
                dependency_fingerprint=acceptance_dependency_fingerprint(video.asset_id, spec.record_id, None),
            )
        ),
    )
    verdict = append_record(
        project,
        ClipVerdict(
            **verdict_kwargs(
                project_id=project_id,
                asset_hash=video.asset_id,
                acceptance_spec_id=spec.record_id,
                disposition="approved",
                defect_ids=(),
                created_by="human:editor",
                review_decision_id=decision.record_id,
            )
        ),
    )
    return project, video, audio, spec, verdict


def _stored_approval(project, **overrides):
    from kinocut.contracts.review import ReviewDecision
    from kinocut.projectstore import append_record
    from tests.contracts_fixtures import review_decision_kwargs

    values = {
        "project_id": project.project_id,
        "target_ref": "sha256:" + "d" * 64,
        "dependency_fingerprint": "sha256:" + "e" * 64,
    }
    values.update(overrides)
    return append_record(project, ReviewDecision(**review_decision_kwargs(**values)))


def test_acceptance_resolves_only_active_stored_records(tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, _, _, spec, verdict = _governed_project(tmp_path, sample_video, sample_audio)
    result = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=[verdict.record_id],
    )
    assert result["report"]["accepted"] is True

    missing = "sha256:" + "f" * 64
    with pytest.raises(MCPVideoError, match="stored"):
        run_wave3_operation(
            "acceptance_eval",
            project_dir=str(project.root),
            acceptance_spec_id=spec.record_id,
            verdict_ids=[missing],
        )
    with pytest.raises(MCPVideoError, match="stored"):
        run_wave3_operation(
            "acceptance_eval",
            project_dir=str(project.root),
            acceptance_spec_id=missing,
            verdict_ids=[verdict.record_id],
        )
    with pytest.raises(MCPVideoError) as fabricated:
        run_wave3_operation(
            "acceptance_eval",
            project_dir=str(project.root),
            spec=spec.model_dump(mode="json"),
            verdicts=[verdict.model_dump(mode="json")],
        )
    assert fabricated.value.code == "wave3_input_invalid"


def test_verdict_surface_requires_active_stored_asset_and_spec(tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from tests.contracts_fixtures import verdict_kwargs

    project, video, _, spec, _ = _governed_project(tmp_path, sample_video, sample_audio)
    payload = verdict_kwargs(
        project_id=project.project_id,
        asset_hash=video.asset_id,
        acceptance_spec_id=spec.record_id,
        disposition="rejected",
    )
    result = run_wave3_operation("verdict", project_dir=str(project.root), verdict=payload)
    assert result["verdict"]["record_id"] is not None

    payload["asset_hash"] = "sha256:" + "f" * 64
    with pytest.raises(MCPVideoError, match="stored"):
        run_wave3_operation("verdict", project_dir=str(project.root), verdict=payload)


def test_acceptance_rejects_superseded_and_foreign_verdicts(tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.contracts.acceptance import GenerationAcceptanceSpec
    from kinocut.contracts.verdict import ClipVerdict
    from kinocut.projectstore import append_record
    from tests.contracts_fixtures import acceptance_spec_kwargs, verdict_kwargs

    project, video, _, spec, verdict = _governed_project(tmp_path, sample_video, sample_audio)
    replacement = append_record(
        project,
        ClipVerdict(
            **verdict_kwargs(
                project_id=project.project_id,
                asset_hash=video.asset_id,
                acceptance_spec_id=spec.record_id,
                disposition="rejected",
                supersedes=verdict.record_id,
            )
        ),
    )
    foreign_spec = append_record(
        project,
        GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project.project_id, spec_id="spec-foreign")),
    )
    foreign = append_record(
        project,
        ClipVerdict(
            **verdict_kwargs(
                project_id=project.project_id,
                asset_hash=video.asset_id,
                acceptance_spec_id=foreign_spec.record_id,
                disposition="approved",
            )
        ),
    )
    for verdict_id in (verdict.record_id, foreign.record_id):
        with pytest.raises(MCPVideoError):
            run_wave3_operation(
                "acceptance_eval",
                project_dir=str(project.root),
                acceptance_spec_id=spec.record_id,
                verdict_ids=[verdict_id],
            )
    assert replacement.record_id != verdict.record_id


def test_body_swap_requires_project_bound_active_inputs(monkeypatch, tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.client import Client
    from kinocut.projectstore import ingest_asset, open_project

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    video_path = str(project.root / video.original_location)
    audio_path = str(project.root / audio.original_location)
    monkeypatch.setattr(
        "kinocut.engine_body_swap.body_swap",
        lambda *args, **kwargs: {"output_path": args[2], "preservation_proofs": []},
    )
    signature = inspect.signature(Client.body_swap)
    assert signature.parameters["project_dir"].default is inspect.Parameter.empty
    result = run_wave3_operation(
        "body_swap",
        project_dir=str(project.root),
        video_source=video_path,
        audio_source=audio_path,
        output_path=str(tmp_path / "out.mp4"),
        duration_policy=None,
        authorization_decision_ids=[],
    )
    assert result["success"] is True

    unrelated = open_project(tmp_path / "unrelated")
    with pytest.raises(MCPVideoError, match="stored"):
        run_wave3_operation(
            "body_swap",
            project_dir=str(unrelated.root),
            video_source=video_path,
            audio_source=audio_path,
            output_path=str(tmp_path / "foreign.mp4"),
            duration_policy=None,
            authorization_decision_ids=[],
        )

    foreign = open_project(tmp_path / "foreign")
    foreign_video = ingest_asset(foreign, sample_video)
    with pytest.raises(MCPVideoError, match="stored"):
        run_wave3_operation(
            "body_swap",
            project_dir=str(foreign.root),
            video_source=str(foreign.root / foreign_video.original_location),
            audio_source=audio_path,
            output_path=str(tmp_path / "cross-project.mp4"),
            duration_policy=None,
            authorization_decision_ids=[],
        )


@pytest.mark.parametrize("source_name", ("video", "audio"))
def test_body_swap_rejects_stored_input_mutated_before_call(
    monkeypatch, tmp_path, sample_video, sample_audio, source_name
):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    paths = {
        "video": project.root / video.original_location,
        "audio": project.root / audio.original_location,
    }
    paths[source_name].write_bytes(b"mutated after canonical ingest")
    rendered = False

    def forbidden_render(*args, **kwargs):
        nonlocal rendered
        rendered = True
        return {"output_path": args[2], "preservation_proofs": []}

    monkeypatch.setattr("kinocut.engine_body_swap.body_swap", forbidden_render)
    output = tmp_path / f"mutated-{source_name}.mp4"
    with pytest.raises(MCPVideoError) as exc:
        run_wave3_operation(
            "body_swap",
            project_dir=str(project.root),
            video_source=str(paths["video"]),
            audio_source=str(paths["audio"]),
            output_path=str(output),
            duration_policy=None,
            authorization_decision_ids=[],
        )
    assert exc.value.code == "wave3_asset_integrity_failed"
    assert str(paths[source_name]) not in str(exc.value)
    assert rendered is False
    assert not output.exists()


@pytest.mark.parametrize("source_name", ("video", "audio"))
def test_body_swap_catches_source_mutation_during_renderer_handoff(
    monkeypatch, tmp_path, sample_video, sample_audio, source_name
):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    paths = {
        "video": project.root / video.original_location,
        "audio": project.root / audio.original_location,
    }
    output = tmp_path / f"handoff-{source_name}.mp4"

    monkeypatch.setattr("kinocut.engine_body_swap._get_video_duration", lambda path, **kwargs: 1.0)
    monkeypatch.setattr("kinocut.engine_body_swap._precheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "kinocut.engine_body_swap._audio_fingerprint",
        lambda path, **kwargs: "sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        "kinocut.engine_body_swap._proof",
        lambda *args, **kwargs: type("Proof", (), {"model_dump": lambda self, **options: {"verdict": "preserved"}})(),
    )

    def mutate_during_render(args, **kwargs):
        paths[source_name].write_bytes(b"mutated during renderer handoff")
        Path(args[-1]).write_bytes(b"must be removed")

    monkeypatch.setattr("kinocut.engine_body_swap._run_ffmpeg", mutate_during_render)
    with pytest.raises(MCPVideoError) as exc:
        run_wave3_operation(
            "body_swap",
            project_dir=str(project.root),
            video_source=str(paths["video"]),
            audio_source=str(paths["audio"]),
            output_path=str(output),
            duration_policy=None,
            authorization_decision_ids=[],
        )
    assert exc.value.code == "wave3_asset_integrity_failed"
    assert str(paths[source_name]) not in str(exc.value)
    assert not output.exists()


@pytest.mark.parametrize("source_name", ("video", "audio"))
@pytest.mark.parametrize("attack", ("mutate_restore", "replace_restore"))
@pytest.mark.skipif(
    not immutable_verified_snapshot_available(),
    reason="immutable verified source snapshots are unavailable",
)
def test_body_swap_renderer_consumes_verified_private_snapshots(
    monkeypatch, tmp_path, sample_video, sample_audio, source_name, attack
):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    canonical = {
        "video": project.root / video.original_location,
        "audio": project.root / audio.original_location,
    }
    selected = canonical[source_name]
    verified_bytes = selected.read_bytes()
    output = tmp_path / f"snapshot-{source_name}-{attack}.mp4"
    observed_input = None
    inherited_fds = ()
    rewritable = True
    replaceable = True

    monkeypatch.setattr("kinocut.engine_body_swap._get_video_duration", lambda path, **kwargs: 1.0)
    monkeypatch.setattr("kinocut.engine_body_swap._precheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "kinocut.engine_body_swap._audio_fingerprint",
        lambda path, **kwargs: "sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        "kinocut.engine_body_swap._proof",
        lambda *args, **kwargs: type("Proof", (), {"model_dump": lambda self, **options: {"verdict": "preserved"}})(),
    )

    def transient_attack(args, *, pass_fds=()):
        nonlocal inherited_fds, observed_input, replaceable, rewritable
        renderer_input = Path(args[1 if source_name == "video" else 3])
        inherited_fds = pass_fds
        if attack == "mutate_restore":
            selected.write_bytes(b"transient hostile bytes")
            observed = renderer_input.read_bytes()
            selected.write_bytes(verified_bytes)
        else:
            backup = tmp_path / f"{source_name}.verified-backup"
            replacement = tmp_path / f"{source_name}.hostile-replacement"
            selected.replace(backup)
            replacement.write_bytes(b"transient replacement bytes")
            replacement.replace(selected)
            observed = renderer_input.read_bytes()
            selected.unlink()
            backup.replace(selected)
        observed_input = renderer_input
        try:
            writable_fd = os.open(renderer_input, os.O_WRONLY)
            try:
                os.write(writable_fd, b"hostile")
            finally:
                os.close(writable_fd)
        except OSError:
            rewritable = False
        renamed = Path(str(renderer_input) + ".hostile")
        try:
            renderer_input.rename(renamed)
        except OSError:
            replaceable = False
        else:
            renamed.rename(renderer_input)
        Path(args[-1]).write_bytes(observed)

    monkeypatch.setattr("kinocut.engine_body_swap._run_ffmpeg", transient_attack)
    result = run_wave3_operation(
        "body_swap",
        project_dir=str(project.root),
        video_source=str(canonical["video"]),
        audio_source=str(canonical["audio"]),
        output_path=str(output),
        duration_policy=None,
        authorization_decision_ids=[],
    )
    assert result["success"] is True
    assert observed_input is not None
    assert observed_input.resolve() != selected.resolve()
    assert str(observed_input).startswith("/dev/fd/")
    assert int(observed_input.name) in inherited_fds
    assert rewritable is False
    assert replaceable is False
    assert not observed_input.exists()
    assert output.read_bytes() == verified_bytes
    assert not list(tmp_path.glob(".body-swap.*"))


def test_body_swap_cleanup_failure_prevents_final_publish(monkeypatch, tmp_path, sample_video, sample_audio):
    import kinocut.engine_body_swap as engine
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    original_manager = engine.tempfile.TemporaryDirectory

    class CleanupFailure:
        def __init__(self, *args, **kwargs):
            self.manager = original_manager(*args, **kwargs)

        def __enter__(self):
            return self.manager.__enter__()

        def __exit__(self, *args):
            self.manager.__exit__(*args)
            raise OSError("simulated cleanup failure")

    monkeypatch.setattr(engine.tempfile, "TemporaryDirectory", CleanupFailure)
    monkeypatch.setattr(engine, "_get_video_duration", lambda path, **kwargs: 1.0)
    monkeypatch.setattr(engine, "_precheck", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_audio_fingerprint", lambda path, **kwargs: "sha256:" + "a" * 64)
    monkeypatch.setattr(
        engine,
        "_proof",
        lambda *args, **kwargs: type("Proof", (), {"model_dump": lambda self, **options: {"verdict": "preserved"}})(),
    )
    monkeypatch.setattr(
        engine,
        "_run_ffmpeg",
        lambda args, **kwargs: Path(args[-1]).write_bytes(b"verified render"),
    )
    output = tmp_path / "cleanup-failure.mp4"
    with pytest.raises(MCPVideoError) as exc:
        run_wave3_operation(
            "body_swap",
            project_dir=str(project.root),
            video_source=str(project.root / video.original_location),
            audio_source=str(project.root / audio.original_location),
            output_path=str(output),
            duration_policy=None,
            authorization_decision_ids=[],
        )
    assert exc.value.error_type == "processing_error"
    assert not output.exists()
    assert not list(tmp_path.glob(".body-swap.*"))


def test_body_swap_snapshot_setup_failure_leaves_no_private_residue(monkeypatch, tmp_path, sample_video, sample_audio):
    import kinocut.engine_body_swap as engine
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)

    def fail_snapshot(*args, **kwargs):
        raise MCPVideoError(
            "snapshot setup failed",
            error_type="processing_error",
            code="snapshot_setup_failed",
        )

    monkeypatch.setattr(engine, "copy_verified_snapshot", fail_snapshot)
    with pytest.raises(MCPVideoError):
        run_wave3_operation(
            "body_swap",
            project_dir=str(project.root),
            video_source=str(project.root / video.original_location),
            audio_source=str(project.root / audio.original_location),
            output_path=str(tmp_path / "setup-failure.mp4"),
            duration_policy=None,
            authorization_decision_ids=[],
        )
    assert not list(tmp_path.glob(".body-swap.*"))


def test_body_swap_second_snapshot_failure_closes_first_descriptor(monkeypatch, tmp_path, sample_video, sample_audio):
    import kinocut.engine_body_swap as engine
    from kinocut.source_identity import VerifiedSource, stream_source_identity

    video_identity = stream_source_identity(sample_video)
    audio_identity = stream_source_identity(sample_audio)
    first_fd = os.open(sample_video, os.O_RDONLY)
    calls = 0

    def fail_second_snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return VerifiedSource(first_fd, video_identity)
        raise MCPVideoError(
            "second snapshot setup failed",
            error_type="validation_error",
            code="source_identity_changed",
        )

    monkeypatch.setattr(engine, "copy_verified_snapshot", fail_second_snapshot)
    output = tmp_path / "second-setup-failure.mp4"
    try:
        with pytest.raises(MCPVideoError, match="second snapshot"):
            engine._guarded_render(
                sample_video,
                sample_audio,
                str(output),
                None,
                None,
                (),
                (video_identity, audio_identity),
            )
        with pytest.raises(OSError):
            os.fstat(first_fd)
    finally:
        with suppress(OSError):
            os.close(first_fd)

    assert calls == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".body-swap.*"))


@pytest.mark.parametrize("operation", ("body_swap", "salvage"))
def test_wave3_authorization_ids_must_be_active_same_project_human_approvals(
    monkeypatch, tmp_path, sample_video, sample_audio, operation
):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.projectstore import open_project

    project, video, audio, spec, _ = _governed_project(tmp_path, sample_video, sample_audio)
    nonhuman = _stored_approval(project, created_by="agent")
    rejected = _stored_approval(
        project,
        decision="reject",
        target_ref="sha256:" + "c" * 64,
    )
    superseded = _stored_approval(
        project,
        target_ref="sha256:" + "b" * 64,
    )
    _stored_approval(
        project,
        target_ref="sha256:" + "b" * 64,
        supersedes=superseded.record_id,
    )
    foreign_project = open_project(tmp_path / "foreign-authorization")
    foreign = _stored_approval(foreign_project)
    missing = "sha256:" + "f" * 64
    rendered = False

    def forbidden_render(*args, **kwargs):
        nonlocal rendered
        rendered = True
        return {"output_path": str(tmp_path / "forbidden.mp4"), "preservation_proofs": []}

    if operation == "body_swap":
        monkeypatch.setattr("kinocut.engine_body_swap.body_swap", forbidden_render)
        base = {
            "project_dir": str(project.root),
            "video_source": str(project.root / video.original_location),
            "audio_source": str(project.root / audio.original_location),
            "output_path": str(tmp_path / "body-out.mp4"),
            "duration_policy": None,
        }
    else:
        monkeypatch.setattr("kinocut.aivideo.salvage.create_salvage_derivative", forbidden_render)
        base = {
            "project_dir": str(project.root),
            "source_asset_id": video.asset_id,
            "recipe": "still_frame",
            "policy": {"timestamp": 0.1},
            "acceptance_spec_id": spec.record_id,
        }

    for decision_id in (missing, superseded.record_id, foreign.record_id, nonhuman.record_id, rejected.record_id):
        with pytest.raises(MCPVideoError) as exc:
            run_wave3_operation(operation, **base, authorization_decision_ids=[decision_id])
        assert exc.value.code == "wave3_authorization_invalid"
        assert str(project.root) not in str(exc.value)
    assert rendered is False
    assert not Path(base.get("output_path", tmp_path / "forbidden.mp4")).exists()


def test_wave3_authorization_accepts_active_stored_human_approval(monkeypatch, tmp_path, sample_video, sample_audio):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, video, audio, _, _ = _governed_project(tmp_path, sample_video, sample_audio)
    approval = _stored_approval(project)
    captured = {}

    def render(*args, **kwargs):
        captured.update(kwargs)
        return {"output_path": args[2], "preservation_proofs": []}

    monkeypatch.setattr("kinocut.engine_body_swap.body_swap", render)
    result = run_wave3_operation(
        "body_swap",
        project_dir=str(project.root),
        video_source=str(project.root / video.original_location),
        audio_source=str(project.root / audio.original_location),
        output_path=str(tmp_path / "approved.mp4"),
        duration_policy=None,
        authorization_decision_ids=[approval.record_id],
    )
    assert result["success"] is True
    assert captured["authorization_decision_ids"] == (approval.record_id,)
