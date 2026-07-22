"""Cross-surface tests for the ``kino shorts`` CLI adapter.

These tests exercise the runtime argparse/handler path, not the orchestrator's
business logic (which is owned by :mod:`kinocut.product.shorts` and tested
separately). Every test hermetically ``monkeypatch.setattr``s a fake
``shorts_plan`` / ``shorts_review`` on the product module so the suite stays
green before / after the orchestrator lands, and so a fail mode in one
function cannot bleed across cases.

Acceptance coverage (per the assignment):

* Runtime parser path (``build_parser().parse_args``).
* Runtime handler path (``handle_shorts_commands`` and CLI entry point).
* Default no-render semantics: ``shorts_plan`` is called, ``shorts_review``
  is not.
* Explicit approved-decisions path (``--decisions`` with a JSON file).
* JSON output (``--format json``) round-trip of the dict.
* Invalid input surfaces a plain-language ``MCPVideoError`` with a
  ``problem / cause / recovery`` envelope.
* Default platform set is the canonical youtube-shorts + instagram-reel pair.
* Help text contains no FFmpeg / model / weight jargon.

Tests do not run binaries; ``kinocut.product.shorts`` is a required name
whose real implementation is shipped by the orchestrator sibling agent. When
that module lands, the same tests pass against the real implementation by
swapping ``monkeypatch.setattr`` for the real module.
"""

from __future__ import annotations

import contextlib
import json
import sys
import types
from typing import Any

import pytest


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _build_shorts_argv(*extra: str, input_path: str = "/tmp/source.mp4") -> list[str]:
    """Return an argv tail that lands on the ``shorts`` subcommand."""

    return ["shorts", input_path, *extra]


def _run_cli(monkeypatch, capsys, *args: str) -> tuple[int, Any]:
    """Invoke the CLI entry point via the same seam the inspection suite uses."""

    from kinocut.__main__ import main

    monkeypatch.setattr("sys.argv", ["kino", "--format", "json", *args])
    code = 0
    try:
        main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    stream = capsys.readouterr()
    payload = stream.out or stream.err
    try:
        return code, json.loads(payload)
    except json.JSONDecodeError:
        return code, payload


def _install_fake_orchestrator(
    monkeypatch,
    *,
    plan_result: Any | None = None,
    plan_kwargs_capture: dict[str, Any] | None = None,
    review_kwargs_capture: dict[str, Any] | None = None,
    review_result: Any | None = None,
    raise_on_plan: BaseException | None = None,
    raise_on_review: BaseException | None = None,
):
    """Replace ``kinocut.product.shorts`` with a tiny stub module.

    Returns a handle that lets each test inspect capture dicts after the call.
    The stub deliberately does NOT import anything from the real orchestrator
    so the suite keeps passing while :mod:`kinocut.product.shorts` is still
    landing.
    """

    captured = {
        "plan_calls": [],
        "review_calls": [],
        "propose_calls": [],
        "plan_result": plan_result,
        "plan_kwargs_capture": plan_kwargs_capture,
        "review_kwargs_capture": review_kwargs_capture,
    }

    def fake_plan(source_path: str, **kwargs: Any):
        captured["plan_calls"].append((source_path, kwargs))
        if raise_on_plan is not None:
            raise raise_on_plan
        if plan_kwargs_capture is not None:
            plan_kwargs_capture.update(kwargs)
        if plan_result is not None:
            return plan_result
        return {
            "job_id": "job-fake",
            "status": "proposed",
            "intake": {"duration": 12.5},
            "proposals": [],
            "manifest_path": "/tmp/manifest.json",
        }

    def fake_review(job_id: str, proposal_id: str, decision: str, evidence_ref):
        captured["review_calls"].append(
            {"job_id": job_id, "proposal_id": proposal_id, "decision": decision, "evidence_ref": evidence_ref}
        )
        if raise_on_review is not None:
            raise raise_on_review
        if review_kwargs_capture is not None:
            review_kwargs_capture.update(captured["review_calls"][-1])
        return review_result if review_result is not None else {"status": "reviewed"}

    def fake_propose(job_id: str, proposal_id: str, **kwargs: Any):
        captured["propose_calls"].append({"job_id": job_id, "proposal_id": proposal_id, **kwargs})
        return {"status": "reviewed", "proposal_id": proposal_id}

    def fake_render(job_id: str, candidate_id: str, **kwargs: Any):
        captured.setdefault("render_calls", []).append((job_id, candidate_id, kwargs))
        return {"job_id": job_id, "candidate_id": candidate_id, "status": "rendered", "external_posting": False}

    def fake_package(job_id: str, candidate_id: str, **kwargs: Any):
        captured.setdefault("package_calls", []).append((job_id, candidate_id, kwargs))
        return {"job_id": job_id, "candidate_id": candidate_id, "status": "packaged", "external_posting": False}

    fake_module = types.ModuleType("kinocut.product.shorts")
    fake_module.shorts_plan = fake_plan  # type: ignore[attr-defined]
    fake_module.shorts_review = fake_review  # type: ignore[attr-defined]
    fake_module.shorts_propose = fake_propose  # type: ignore[attr-defined]
    fake_module.shorts_render = fake_render  # type: ignore[attr-defined]
    fake_module.shorts_package = fake_package  # type: ignore[attr-defined]

    # ``kinocut.product.shorts`` may not yet exist on disk while the
    # orchestrator sibling is landing; install the stub in :data:`sys.modules`
    # so the handler's ``from ..product import shorts`` lookup resolves to it.
    monkeypatch.setitem(sys.modules, "kinocut.product.shorts", fake_module)
    import kinocut.product as product_pkg

    monkeypatch.setattr(product_pkg, "shorts", fake_module, raising=False)
    return captured


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_shorts_parser_accepts_canonical_input_only():
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(_build_shorts_argv())
    assert args.command == "shorts"
    assert args.input == "/tmp/source.mp4"
    assert args.platform is None
    assert args.max_clip_seconds is None
    assert args.min_clip_seconds is None
    # ``subject_reframe`` was removed: the CLI no longer accepts the flag, and
    # the orchestrator does not advertise automatic subject tracking. The
    # default proposal path always uses safe padded 9:16 composition.
    assert not hasattr(args, "subject_reframe")
    assert args.burned_captions is None  # default; orchestrator picks
    assert args.captions_editable is True
    assert args.output_dir is None
    assert args.resume_job_id is None
    assert args.decisions is None


def test_shorts_parser_accepts_approval_and_resume_flags(tmp_path):
    from kinocut.cli.parser import build_parser

    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text("[]", encoding="utf-8")
    args = build_parser().parse_args(
        _build_shorts_argv(
            "--platform",
            "youtube-shorts",
            "--max-clip-seconds",
            "45",
            "--min-clip-seconds",
            "5",
            "--captions-editable",
            "--output-dir",
            str(tmp_path / "out"),
            "--resume-job-id",
            "job-7",
            "--decisions",
            str(decisions_path),
            "--no-burned-captions",
            input_path=str(tmp_path / "source.mov"),
        )
    )
    assert args.command == "shorts"
    assert args.input == str(tmp_path / "source.mov")
    assert args.platform == ["youtube-shorts"]
    assert args.max_clip_seconds == 45.0
    assert args.min_clip_seconds == 5.0
    # ``subject_reframe`` was removed; the parser must not expose the flag.
    assert not hasattr(args, "subject_reframe")
    assert args.captions_editable is True
    assert args.output_dir == str(tmp_path / "out")
    assert args.resume_job_id == "job-7"
    assert args.decisions == str(decisions_path)
    assert args.burned_captions is False


def test_shorts_parser_render_and_package_inputs_are_explicit():
    from kinocut.cli.parser import build_parser

    render = build_parser().parse_args(
        [
            "shorts",
            "--render",
            "--resume-job-id",
            "job-1",
            "--candidate-id",
            "c1",
            "--output-dir",
            "plans",
            "--output",
            "out.mp4",
        ]
    )
    assert render.input is None
    assert render.render is True
    package = build_parser().parse_args(
        [
            "shorts",
            "--package",
            "--resume-job-id",
            "job-1",
            "--candidate-id",
            "c1",
            "--output-dir",
            "plans",
            "--output",
            "package",
        ]
    )
    assert package.package is True


def test_render_stage_calls_shared_function_and_emits_json(monkeypatch, capsys):
    capture = _install_fake_orchestrator(monkeypatch)
    code, payload = _run_cli(
        monkeypatch,
        capsys,
        "shorts",
        "--render",
        "--resume-job-id",
        "job-1",
        "--candidate-id",
        "c1",
        "--output-dir",
        "plans",
        "--output",
        "out.mp4",
    )
    assert code == 0
    assert payload["status"] == "rendered"
    assert payload["external_posting"] is False
    assert capture["render_calls"] == [("plans/job-1.plan.json", "c1", {"output_path": "out.mp4"})]
    assert capture["plan_calls"] == []
    assert capture["review_calls"] == []


def test_package_stage_calls_shared_function_and_emits_json(monkeypatch, capsys):
    capture = _install_fake_orchestrator(monkeypatch)
    code, payload = _run_cli(
        monkeypatch,
        capsys,
        "shorts",
        "--package",
        "--resume-job-id",
        "job-1",
        "--candidate-id",
        "c1",
        "--output-dir",
        "plans",
        "--output",
        "package",
    )
    assert code == 0
    assert payload["status"] == "packaged"
    assert payload["external_posting"] is False
    assert capture["package_calls"] == [("plans/job-1.plan.json", "c1", {"package_dir": "package"})]


@pytest.mark.parametrize(
    ("stage", "code"), [("--render", "missing_render_input"), ("--package", "missing_package_input")]
)
def test_explicit_stages_require_job_candidate_and_output(monkeypatch, capsys, stage, code):
    _install_fake_orchestrator(monkeypatch)
    exit_code, payload = _run_cli(monkeypatch, capsys, "shorts", stage)
    assert exit_code == 1
    assert payload["error"]["code"] == code
    assert "--resume-job-id" in payload["error"]["message"]
    assert "--candidate-id" in payload["error"]["message"]
    assert "--output" in payload["error"]["message"]
    assert "--output-dir" in payload["error"]["message"]


def test_shorts_parser_bounds_platform_choices_to_canonical_pair():
    from kinocut.cli.parser import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(_build_shorts_argv("--platform", "tiktok"))


def test_shorts_help_text_avoids_engine_and_model_jargon():
    from kinocut.cli.parser import build_parser

    parser = build_parser()
    # argparse exits 0 on --help but we only need the rendered text.
    with contextlib.suppress(SystemExit):
        parser.parse_args(["shorts", "--help"])

    formatter = parser.formatter_class(parser.prog)
    # Render the shorts subparser's help by walking the subparsers action.
    sub_action = next(action for action in parser._actions if action.dest == "command")
    shorts_action = sub_action.choices["shorts"]
    rendered = formatter.format_help()  # outer parser
    rendered += "\n" + shorts_action.format_help()

    # FFmpeg / Whisper / model jargon must NOT leak into operator-facing help.
    # ``render`` and ``media`` are everyday English and intentionally allowed
    # (the help text must explain that the default ``shorts`` command does
    # *not* render, and that operators move to a separate render entrypoint).
    forbidden = (
        "ffmpeg",
        "ffprobe",
        "whisper",
        "drawtext",
        "tensor",
    )
    lowered = rendered.lower()
    assert "weights" not in lowered
    assert "base model" not in lowered
    for term in forbidden:
        assert term not in lowered, f"help text mentions banned term: {term!r}"


def test_shorts_command_is_registered_and_unique_in_the_global_parser():
    from kinocut.cli.parser import build_parser

    sub_action = next(action for action in build_parser()._actions if action.dest == "command")
    names = sorted(sub_action.choices)
    assert names.count("shorts") == 1


# --------------------------------------------------------------------------- #
# Default no-render semantics
# --------------------------------------------------------------------------- #


def test_default_invocation_stops_after_proposals_and_does_not_call_review(monkeypatch, capsys):
    capture = _install_fake_orchestrator(monkeypatch)

    code, payload = _run_cli(monkeypatch, capsys, *_build_shorts_argv())

    assert code == 0
    assert payload["job_id"] == "job-fake"
    assert payload["status"] == "proposed"
    assert capture["plan_calls"], "shorts_plan must be called by default"
    assert capture["review_calls"] == [], "shorts_review must NOT be called by default"


def test_default_invocation_forwards_canonical_platform_defaults(monkeypatch, capsys):
    captured_kwargs: dict[str, Any] = {}
    _install_fake_orchestrator(
        monkeypatch,
        plan_result={"job_id": "job-x", "status": "proposed"},
        plan_kwargs_capture=captured_kwargs,
    )

    code, payload = _run_cli(monkeypatch, capsys, *_build_shorts_argv())

    assert code == 0
    platforms = captured_kwargs["platforms"]
    assert tuple(platforms) == ("youtube-shorts", "instagram-reel")
    # The JSON payload is the orchestrator's plan dict; verify the CLI forwarded
    # the plan and left the orchestrator's shape intact. Platforms live in the
    # captured kwargs so the adapter layer is reasoned about independently.
    assert payload["job_id"] == "job-x"
    assert payload["status"] == "proposed"
    assert captured_kwargs["burned_captions"] is False
    # ``subject_reframe`` was removed; the handler must not forward it.
    assert "subject_reframe" not in captured_kwargs
    assert captured_kwargs["captions_editable"] is True
    assert captured_kwargs["resume_job_id"] is None


def test_default_invocation_forwards_explicit_flags(monkeypatch, capsys, tmp_path):
    captured_kwargs: dict[str, Any] = {}
    _install_fake_orchestrator(
        monkeypatch,
        plan_kwargs_capture=captured_kwargs,
    )

    argv = _build_shorts_argv(
        "--max-clip-seconds",
        "30",
        "--min-clip-seconds",
        "4",
        "--no-burned-captions",
        "--captions-editable",
        "--platform",
        "instagram-reel",
        "--output-dir",
        str(tmp_path / "out"),
        "--resume-job-id",
        "job-1",
        input_path=str(tmp_path / "src.mp4"),
    )
    code, _payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 0
    assert captured_kwargs["max_clip_seconds"] == 30.0
    assert captured_kwargs["min_clip_seconds"] == 4.0
    # ``subject_reframe`` was removed; the handler must not forward it.
    assert "subject_reframe" not in captured_kwargs
    assert captured_kwargs["burned_captions"] is False
    assert captured_kwargs["captions_editable"] is True
    assert list(captured_kwargs["platforms"]) == ["instagram-reel"]
    assert captured_kwargs["output_dir"] == str(tmp_path / "out")
    assert captured_kwargs["resume_job_id"] == "job-1"


def test_default_invocation_does_not_render_any_media(monkeypatch, capsys):
    """Guard against a future contributor accidentally adding a render path."""

    capture = _install_fake_orchestrator(
        monkeypatch,
        plan_result={
            "job_id": "job-safe",
            "status": "proposed",
            "proposals": [
                {
                    "proposal_id": "p1",
                    "platform": "youtube-shorts",
                    "start": 0.0,
                    "end": 12.5,
                    "suggested_title": "Hook",
                }
            ],
        },
    )

    _run_cli(
        monkeypatch,
        capsys,
        *_build_shorts_argv(input_path="/tmp/source.mp4"),
    )

    # No render path should be active even when proposals carry media params.
    plan_kwargs = capture["plan_calls"][0][1]
    assert "render" not in plan_kwargs
    assert "render_path" not in plan_kwargs
    assert "output" not in plan_kwargs


# --------------------------------------------------------------------------- #
# Explicit approved-decisions path
# --------------------------------------------------------------------------- #


def test_decisions_path_records_review_without_rendering(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            [
                {"proposal_id": "p1", "decision": "approve", "evidence_ref": "ev-1"},
                {"proposal_id": "p2", "decision": "reject", "evidence_ref": "ev-2"},
            ]
        ),
        encoding="utf-8",
    )
    capture = _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-99",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 0
    assert payload["job_id"] == "job-99"
    assert payload["proposal_id"] == "p1"
    assert {d["decision"] for d in payload["decisions"]} == {"approve", "reject"}
    assert payload["failures"] == []
    assert len(capture["review_calls"]) == 2
    # The plan was re-hydrated once via resume_job_id.
    assert len(capture["plan_calls"]) == 1


def test_edit_decision_is_recorded_once_without_duplicate_review(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            [
                {
                    "proposal_id": "p-trim",
                    "decision": "trim",
                    "edit": {"action": "trim", "start": 1.0, "end": 4.0},
                    "evidence_ref": "operator",
                }
            ]
        ),
        encoding="utf-8",
    )
    capture = _install_fake_orchestrator(monkeypatch)
    code, payload = _run_cli(
        monkeypatch,
        capsys,
        "shorts",
        str(tmp_path / "source.mp4"),
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-edit",
    )
    assert code == 0
    assert payload["failures"] == []
    assert capture["review_calls"] == []
    assert capture["propose_calls"] == [
        {
            "job_id": "job-edit",
            "proposal_id": "p-trim",
            "edit": {
                "action": "trim",
                "start": 1.0,
                "end": 4.0,
                "evidence_ref": "operator",
            },
        }
    ]


def test_decisions_path_accepts_wrapped_payload(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            {
                "decisions": [
                    {"proposal_id": "p-wrapped", "decision": "preview"},
                ]
            }
        ),
        encoding="utf-8",
    )
    capture = _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-w",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 0
    assert payload["decisions"][0]["proposal_id"] == "p-wrapped"
    assert capture["review_calls"][0]["proposal_id"] == "p-wrapped"


def test_decisions_path_requires_resume_job_id(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text("[]", encoding="utf-8")
    _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        input_path=str(tmp_path / "source.mp4"),
    )

    code, payload = _run_cli(monkeypatch, capsys, *argv)
    assert code == 1
    assert payload["error"]["code"] == "missing_resume_job_id"
    # The action description must guide the user without engine/model jargon.
    message = payload["error"]["message"].lower()
    assert "decisions" in message
    assert "resume-job-id" in message


# --------------------------------------------------------------------------- #
# JSON output round-trip
# --------------------------------------------------------------------------- #


def test_shorts_plan_emits_the_dict_unchanged_in_json_mode(monkeypatch, capsys):
    expected = {
        "job_id": "job-json",
        "status": "proposed",
        "intake": {"duration": 9.0, "checksum": "sha256:" + "a" * 64, "problems": []},
        "proposals": [
            {
                "proposal_id": "p-1",
                "platform": "youtube-shorts",
                "start": 1.0,
                "end": 9.0,
                "suggested_title": "First cut",
            }
        ],
        "manifest_path": "/tmp/manifest.json",
    }
    _install_fake_orchestrator(monkeypatch, plan_result=expected)

    code, payload = _run_cli(monkeypatch, capsys, *_build_shorts_argv(input_path="/tmp/source.mp4"))

    assert code == 0
    assert payload == expected


def test_shorts_decisions_emits_the_decisions_payload_in_json_mode(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text('[{"proposal_id": "p-dec", "decision": "trim"}]', encoding="utf-8")
    _install_fake_orchestrator(
        monkeypatch,
        review_result={"status": "reviewed", "proposal_id": "p-dec"},
    )

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-dec",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 0
    assert payload["job_id"] == "job-dec"
    assert payload["decisions"][0]["result"] == {
        "status": "reviewed",
        "proposal_id": "p-dec",
    }


# --------------------------------------------------------------------------- #
# Invalid input / actionable errors
# --------------------------------------------------------------------------- #


def test_decisions_path_rejects_unknown_decision_kind(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text('[{"proposal_id": "p1", "decision": "ship-it-now"}]', encoding="utf-8")
    _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-bad",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 1
    assert payload["error"]["code"] == "invalid_decisions_shape"
    message = payload["error"]["message"].lower()
    assert "decision" in message and "approve" in message


def test_decisions_path_surfaces_missing_file_with_recovery(monkeypatch, capsys, tmp_path):
    _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(tmp_path / "does-not-exist.json"),
        "--resume-job-id",
        "job-missing",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 1
    assert payload["error"]["code"] == "invalid_input"
    message = payload["error"]["message"]
    assert "does-not-exist" in message or "decisions file" in message.lower()


def test_decisions_path_surfaces_invalid_json_with_recovery(monkeypatch, capsys, tmp_path):
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text("{ this is not json", encoding="utf-8")
    _install_fake_orchestrator(monkeypatch)

    argv = _build_shorts_argv(
        "--decisions",
        str(decisions_path),
        "--resume-job-id",
        "job-junk",
        input_path=str(tmp_path / "source.mp4"),
    )
    code, payload = _run_cli(monkeypatch, capsys, *argv)

    assert code == 1
    assert payload["error"]["code"] == "invalid_decisions_json"


def test_orchestrator_failure_propagates_as_actionable_error(monkeypatch, capsys):
    from kinocut.errors import MCPVideoError

    failing_error = MCPVideoError(
        "Probe could not read the source video.",
        error_type="intake_error",
        code="intake_failed",
        suggested_action={
            "auto_fix": False,
            "description": ("Verify the file exists, is readable, and is a known container format."),
        },
    )
    _install_fake_orchestrator(monkeypatch, raise_on_plan=failing_error)

    code, payload = _run_cli(monkeypatch, capsys, *_build_shorts_argv(input_path="/tmp/missing.mov"))

    assert code == 1
    assert payload["error"]["code"] == "intake_failed"
    assert "verify" in payload["error"]["suggested_action"]["description"].lower()


def test_missing_orchestrator_module_is_a_fail_closed_validation_error(monkeypatch, capsys):
    """A missing orchestrator is surfaced as a typed actionable error."""

    import kinocut.cli.handlers_shorts as handlers

    def _missing():
        raise handlers._problem(
            "The shorts orchestrator is unavailable.",
            code="orchestrator_unavailable",
            suggested_action="Install a build that includes the shorts workflow.",
        )

    monkeypatch.setattr(handlers, "_import_product_shorts", _missing)
    code, payload = _run_cli(monkeypatch, capsys, *_build_shorts_argv(input_path="/tmp/source.mp4"))

    assert code == 1
    assert payload["error"]["code"] == "orchestrator_unavailable"
    assert "shorts" in payload["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# Handler direct (no CLI entry) — used in projects that embed the handler.
# --------------------------------------------------------------------------- #


def test_handle_shorts_commands_returns_false_for_other_commands(monkeypatch):
    from kinocut.cli.handlers_shorts import handle_shorts_commands

    args = types.SimpleNamespace(command="rescue-plan")
    assert handle_shorts_commands(args, use_json=True) is False


def test_handle_shorts_commands_dispatches_shorts(monkeypatch, capsys):
    capture = _install_fake_orchestrator(monkeypatch)

    from kinocut.cli.handlers_shorts import handle_shorts_commands
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(_build_shorts_argv(input_path="/tmp/source.mp4"))
    assert handle_shorts_commands(args, use_json=True) is True
    assert capture["plan_calls"], "shorts_plan must be called from the handler"


# --------------------------------------------------------------------------- #
# Sanity: parser/__init__.py wires ``shorts.add_parsers``.
# --------------------------------------------------------------------------- #


def test_shorts_parser_module_registered_in_parser_init():
    from kinocut.cli.parser import build_parser

    sub_action = next(action for action in build_parser()._actions if action.dest == "command")
    assert "shorts" in sub_action.choices


def test_parser_init_exposes_shorts_module_attribute():
    import kinocut.cli.parser as parser_module

    # The shorts submodule is imported for its side-effecting add_parsers.
    assert hasattr(parser_module, "shorts")
