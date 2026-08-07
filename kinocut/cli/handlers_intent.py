"""CLI handlers for intent / watching surface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runner import CommandRunner, _out


def handle_intent_commands(args: Any, *, use_json: bool) -> bool:
    """Handle intent / caption-translate / review CLI commands."""
    runner = CommandRunner(args, use_json)

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

    def _review_run(a: Any, j: bool) -> None:
        from kinocut.watching import run_review

        r = run_review(a.input).to_dict()
        _out(r, j, lambda res: f"review_run {res['verdict']} ({len(res['findings'])} findings)")

    def _review_decide(a: Any, j: bool) -> None:
        from kinocut.watching import decide_review

        run = json.loads(Path(a.review_run_json).read_text(encoding="utf-8"))
        r = decide_review(run, a.decision, a.reason).to_dict()
        _out(r, j, lambda res: f"decision={res['decision']}")

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

    runner.register("intent", _intent)
    runner.register("propose-broll", _broll)
    runner.register("translate-captions", _translate)
    runner.register("language-coverage", _coverage)
    runner.register("review-run", _review_run)
    runner.register("review-decide", _review_decide)
    runner.register("init", _init)
    runner.register("estimate", _estimate)
    runner.register("brand-kit", _brand)
    runner.register("cutfile-validate", _cutfile)
    runner.register("propose-mutations", _mutations)
    return runner.dispatch()
