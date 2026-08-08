"""CLI handlers for intent / watching surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runner import CommandRunner, _out


def handle_intent_commands(args: Any, *, use_json: bool) -> bool:
    """Handle intent / caption-translate / review CLI commands."""
    runner = CommandRunner(args, use_json)
    _register_intent_commands(runner)
    _register_review_commands(runner)
    _register_te_commands(runner)
    _register_multiplier_commands(runner)
    return runner.dispatch()


def _register_intent_commands(runner: CommandRunner) -> None:
    """Register intent, broll, translate, and language-coverage commands."""

    def _intent(a: Any, j: bool) -> None:
        from kinocut.intent import list_intent_verbs, route_intent

        if a.list or not a.verb:
            r = {"artifact_kind": "intent_catalog", "verbs": list_intent_verbs()}
            _out(r, j, lambda res: "\n".join(f"{v['verb']}: {v['summary']}" for v in res["verbs"]))
            return
        params: dict[str, Any] = {}
        if a.params_json:
            params = json.loads(a.params_json)
        plan = route_intent(a.verb, params)
        r = {"artifact_kind": "intent_plan", **plan.to_dict()}
        _out(r, j, lambda res: f"{res['verb']} → {res['next_action']} via {res['compat_tools']}")

    def _broll(a: Any, j: bool) -> None:
        from kinocut.intent import propose_broll

        segments = json.loads(Path(a.segments_json).read_text(encoding="utf-8"))
        proposals = propose_broll(segments, max_proposals=a.max_proposals)
        r = {
            "artifact_kind": "broll_proposals",
            "apply_policy": "human_review_required",
            "proposal_count": len(proposals),
            "proposals": [p.to_dict() for p in proposals],
        }
        _out(r, j, lambda res: f"{res['proposal_count']} b-roll proposals (review required)")

    def _translate(a: Any, j: bool) -> None:
        from kinocut.intent import translate_caption_file

        result = translate_caption_file(
            a.input,
            a.output,
            source_lang=a.source_lang,
            target_lang=a.target_lang,
        )
        _out(result.to_dict(), j, lambda res: f"translated → {res['output_path']} ({res['cue_count']} cues)")

    def _coverage(a: Any, j: bool) -> None:
        from kinocut.intent import language_coverage_report

        r = language_coverage_report()
        _out(
            r,
            j,
            lambda res: " | ".join(
                f"{name}: {'ok' if meta['available'] else 'none'}" for name, meta in res["surfaces"].items()
            ),
        )

    runner.register("intent", _intent)
    runner.register("propose-broll", _broll)
    runner.register("translate-captions", _translate)
    runner.register("language-coverage", _coverage)


def _register_review_commands(runner: CommandRunner) -> None:
    """Register review-run, review-decide, qc-vision, and qc-narrative commands."""

    def _review_run(a: Any, j: bool) -> None:
        from kinocut.watching import run_review

        r = run_review(a.input).to_dict()
        _out(r, j, lambda res: f"review_run {res['verdict']} ({len(res['findings'])} findings)")

    def _review_decide(a: Any, j: bool) -> None:
        from kinocut.watching import decide_review

        run = json.loads(Path(a.review_run_json).read_text(encoding="utf-8"))
        r = decide_review(run, a.decision, a.reason).to_dict()
        _out(r, j, lambda res: f"decision={res['decision']}")

    def _qc_vision(a: Any, j: bool) -> None:
        from kinocut.watching import run_vision_qc

        _out(run_vision_qc(a.input), j, lambda r: f"vision {r['verdict']}")

    def _qc_narrative(a: Any, j: bool) -> None:
        from kinocut.watching import run_narrative_qc

        _out(run_narrative_qc(a.input), j, lambda r: f"narrative {r['verdict']}")

    runner.register("review-run", _review_run)
    runner.register("review-decide", _review_decide)
    runner.register("qc-vision", _qc_vision)
    runner.register("qc-narrative", _qc_narrative)


def _register_te_commands(runner: CommandRunner) -> None:
    """Register init, estimate, brand-kit, cutfile, mutations, publish, hooks, seek commands."""

    def _init(a: Any, j: bool) -> None:
        from kinocut.te import init_project

        r = init_project(a.path, name=a.name, with_cutfile=not a.no_cutfile)
        _out(r, j, lambda res: f"init → {res['path']}")

    def _estimate(a: Any, j: bool) -> None:
        from kinocut.te import estimate_operation

        r = estimate_operation(a.operation, duration_seconds=a.duration, complexity=a.complexity)
        _out(r, j, lambda res: f"{res['operation']}: ~{res['estimated_wall_seconds']}s wall")

    def _brand(a: Any, j: bool) -> None:
        from kinocut.te import BrandKit, load_brand_kit, save_brand_kit

        if a.action == "save":
            r = save_brand_kit(
                a.path,
                BrandKit(name=a.name, primary_color=a.primary, accent_color=a.accent),
            )
        else:
            r = {"artifact_kind": "brand_kit", **load_brand_kit(a.path).to_dict()}
        _out(r, j, lambda res: f"brand_kit {res.get('name')}")

    def _cutfile(a: Any, j: bool) -> None:
        from kinocut.te import load_cutfile

        r = load_cutfile(a.path).to_dict()
        _out(r, j, lambda res: f"cutfile ok name={res['name']} ops={len(res['ops'])}")

    def _mutations(a: Any, j: bool) -> None:
        from kinocut.watching import propose_mutations_from_findings

        findings = json.loads(Path(a.findings_json).read_text(encoding="utf-8"))
        props = propose_mutations_from_findings(findings)
        r = {
            "artifact_kind": "proposed_mutations",
            "apply_policy": "human_review_required",
            "mutation_count": len(props),
            "mutations": [p.to_dict() for p in props],
        }
        _out(r, j, lambda res: f"{res['mutation_count']} proposed mutations")

    def _publish(a: Any, j: bool) -> None:
        from kinocut.te import validate_publish_spec

        r = validate_publish_spec(a.platform, duration_seconds=a.duration, height=a.height, width=a.width)
        _out(r, j, lambda res: f"{res['platform']} {res['verdict']}")

    def _hooks(a: Any, j: bool) -> None:
        from kinocut.te import generate_hook_candidates

        r = generate_hook_candidates(a.topic, count=a.count, language=a.language)
        _out(r, j, lambda res: f"{len(res['titles'])} hook candidates")

    def _seek(a: Any, j: bool) -> None:
        from kinocut.te import frame_to_timestamp, timestamp_to_frame

        if a.frame is not None:
            r = frame_to_timestamp(a.frame, a.fps)
        else:
            r = timestamp_to_frame(float(a.seconds or 0), a.fps)
        _out(r, j, lambda res: f"frame={res['frame']} t={res['seconds']}")

    runner.register("init", _init)
    runner.register("estimate", _estimate)
    runner.register("brand-kit", _brand)
    runner.register("cutfile-validate", _cutfile)
    runner.register("propose-mutations", _mutations)
    runner.register("publish-validate", _publish)
    runner.register("hook-candidates", _hooks)
    runner.register("seek-frame", _seek)


def _register_multiplier_commands(runner: CommandRunner) -> None:
    """Register otio-export, otio-import, review-ui, and edit-session commands."""

    def _otio_export(a: Any, j: bool) -> None:
        from kinocut.multipliers import export_otio_json

        timeline = json.loads(Path(a.timeline_json).read_text(encoding="utf-8"))
        r = export_otio_json(timeline, a.output)
        _out(r, j, lambda res: f"otio → {res['path']}")

    def _otio_import(a: Any, j: bool) -> None:
        from kinocut.multipliers import import_otio_json

        r = import_otio_json(a.path)
        _out(r, j, lambda res: f"timeline {res['timeline_id']} nodes={len(res['nodes'])}")

    def _review_ui(a: Any, j: bool) -> None:
        from kinocut.multipliers import write_review_surface

        r = write_review_surface(a.output_dir)
        _out(r, j, lambda res: f"review ui → {res['html_path']}")

    def _session(a: Any, j: bool) -> None:
        from kinocut.te import session_open, session_step

        if a.action == "open":
            r = session_open(a.path, a.goal)
        else:
            r = session_step(a.path, action=a.step_action, score=a.score)
        _out(r, j, lambda res: f"session improvement={res.get('measured_improvement')}")

    runner.register("otio-export", _otio_export)
    runner.register("otio-import", _otio_import)
    runner.register("review-ui", _review_ui)
    runner.register("edit-session", _session)
