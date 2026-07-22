"""CLI handler for the `kino shorts` orchestrator.

This module is intentionally thin: every decision is delegated to
:mod:`kinocut.product.shorts`, which owns the planning, review, and render
lifecycle. The handler does three things only:

* translate argparse namespace values into orchestrator keyword arguments;
* dispatch to ``shorts_plan`` (default) or ``shorts_review`` (when
  ``--decisions`` was supplied);
* format the resulting JSON dict using the same text/JSON convention as the
  rest of the CLI, and let :class:`MCPVideoError` errors bubble into the
  existing CLI error panel (which already renders problem / cause / recovery).

The handler does not import any engine module, never opens a network
connection, and never authenticates or posts to any platform.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from .formatting import _format_success_panel, _model_dump, console
from .runner import CommandRunner, _out


# Default platforms the CLI advertises when --platform is omitted. Mirrors
# kinocut.product.config.CANONICAL_EXTERNAL_PLATFORMS; duplicated here so the
# CLI surface remains usable even if the product module is not yet installed.
_DEFAULT_PLATFORMS: tuple[str, ...] = ("youtube-shorts", "instagram-reel")


# Decisions that the CLI forwards verbatim to shorts_review. Anything else is
# rejected up-front so a typo never reaches the orchestrator as a silent no-op.
_ALLOWED_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "preview",
        "approve",
        "reject",
        "trim",
        "title_hook_edit",
        "sensitive_unsuitable",
    }
)


def _problem(
    message: str,
    *,
    code: str,
    suggested_action: str | None = None,
) -> Exception:
    """Build a fail-closed :class:`MCPVideoError` with a plain-language message.

    Lazy-imports :mod:`kinocut.errors` so this module remains importable in
    environments where the orchestrator's product module is not present (the
    parser registration must still succeed for ``kino --help`` to list the
    ``shorts`` command).
    """

    from ..errors import MCPVideoError

    action = {"auto_fix": False, "description": suggested_action} if suggested_action else None
    return MCPVideoError(
        message,
        error_type="validation_error",
        code=code,
        suggested_action=action,
    )


def _load_decisions_file(path: str) -> Any:
    """Read and JSON-decode a decisions file with a plain-language error."""

    if not os.path.exists(path):
        raise _problem(
            f"Could not find the decisions file at {path!r}.",
            code="invalid_input",
            suggested_action=(
                "Pass --decisions with the path to a UTF-8 JSON file of "
                "review decisions, or omit --decisions to stop at the proposal."
            ),
        )

    try:
        with open(path, encoding="utf-8", errors="strict") as handle:
            return json.loads(handle.read())
    except UnicodeDecodeError as exc:
        raise _problem(
            f"Decisions file {path!r} is not valid UTF-8: {exc.reason}.",
            code="invalid_decisions_encoding",
            suggested_action=("Re-export the decisions file as UTF-8 (no BOM) and retry."),
        ) from None
    except json.JSONDecodeError as exc:
        raise _problem(
            f"Decisions file {path!r} is not valid JSON: {exc.msg}.",
            code="invalid_decisions_json",
            suggested_action=(
                "Fix the JSON syntax, or run `kino shorts <input>` first to regenerate a clean decisions template."
            ),
        ) from None


def _coerce_decision_entries(payload: Any) -> list[dict[str, Any]]:
    """Coerce a decisions payload into the strict list-of-entries shape.

    Accepts either a top-level list or an object with a ``decisions`` key, so
    authors can paste either a raw array or a review-manifest-shaped wrapper.
    An empty list is valid (the command will simply persist an empty review
    log).
    """

    if isinstance(payload, list):
        entries: list[Any] = payload
    elif isinstance(payload, dict):
        if "decisions" in payload and isinstance(payload["decisions"], list):
            entries = payload["decisions"]
        else:
            entries = [payload]
    else:
        raise _problem(
            f"Decisions JSON must be a list or an object with a 'decisions' key; got {type(payload).__name__}.",
            code="invalid_decisions_shape",
        )

    normalised: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _problem(
                f"Decisions[{index}] must be an object; got {type(entry).__name__}.",
                code="invalid_decisions_shape",
            )
        normalised.append(entry)
    return normalised


def _validate_decision_entry(entry: dict[str, Any]) -> tuple[str, str]:
    """Return ``(proposal_id, decision)`` or raise a plain-language error."""

    proposal_id = entry.get("proposal_id") or entry.get("candidate_id")
    if not isinstance(proposal_id, str) or not proposal_id:
        raise _problem(
            "Each decision entry needs a non-empty 'proposal_id'.",
            code="invalid_decisions_shape",
        )
    decision = entry.get("decision")
    if not isinstance(decision, str) or decision not in _ALLOWED_DECISION_KINDS:
        allowed = ", ".join(sorted(_ALLOWED_DECISION_KINDS))
        raise _problem(
            f"Decision for {proposal_id!r} must be one of: {allowed}.",
            code="invalid_decisions_shape",
        )
    return proposal_id, decision


def _build_plan_kwargs(args: Any) -> dict[str, Any]:
    """Translate the argparse namespace to orchestrator keyword arguments."""

    platforms = list(args.platform) if args.platform else list(_DEFAULT_PLATFORMS)

    return {
        "platforms": platforms,
        "max_clip_seconds": args.max_clip_seconds,
        "min_clip_seconds": args.min_clip_seconds,
        # ``subject_reframe`` was an inert public knob: the orchestrator's
        # current render path always uses safe padded 9:16 composition and
        # never consumes the flag. It is intentionally absent here so the
        # CLI cannot reintroduce a no-op.
        "burned_captions": (False if args.burned_captions is None else bool(args.burned_captions)),
        "captions_editable": bool(args.captions_editable),
        "output_dir": args.output_dir,
        "resume_job_id": args.resume_job_id,
    }


def _format_plan_text(result: Any) -> None:
    """Render a proposal as a plain-language panel with no model jargon."""

    data = _model_dump(result) if hasattr(result, "model_dump") else result
    if not isinstance(data, dict):
        console.print(str(result))
        return

    status = data.get("status") or "proposed"
    job_id = data.get("job_id") or "(unsaved)"
    resumed_from = data.get("resumed_from")
    manifest_path = data.get("manifest_path")

    intake = data.get("intake") or {}
    proposals = data.get("proposals") or []

    lines = [
        f"[bold green]Job:[/bold green] {job_id}",
        f"[bold green]Status:[/bold green] {status}",
    ]
    if isinstance(resumed_from, str) and resumed_from:
        lines.append(f"[bold green]Resumed from:[/bold green] {resumed_from}")
    if isinstance(intake, dict) and intake:
        duration = intake.get("duration")
        if isinstance(duration, (int, float)):
            lines.append(f"[bold green]Duration:[/bold green] {duration:.2f}s")
    proposal_count = len(proposals) if isinstance(proposals, list) else 0
    lines.append(f"[bold green]Proposals:[/bold green] {proposal_count}")

    if isinstance(proposals, list) and proposals:
        lines.append("")
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            pid = proposal.get("proposal_id") or proposal.get("id") or "(unknown)"
            platform = proposal.get("platform") or "(unknown platform)"
            start = proposal.get("start")
            end = proposal.get("end")
            timing = ""
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                timing = f"  [{start:.2f}s -> {end:.2f}s]"
            title = proposal.get("suggested_title") or proposal.get("title") or ""
            title_text = f"  -- {title}" if title else ""
            lines.append(f"  - {pid}  {platform}{timing}{title_text}")

    lines.append("")
    if isinstance(manifest_path, str) and manifest_path:
        lines.append(f"[bold green]Manifest:[/bold green] {manifest_path}")
    lines.append(
        "[bold yellow]No media was rendered. Review the proposals, record "
        "decisions, then run the orchestrator's render entrypoint.[/bold yellow]"
    )

    _format_success_panel(lines, title="Shorts Proposal", border_style="yellow")


def _format_review_text(result: Any) -> None:
    """Render a decisions-recorded result as a plain-language panel."""

    data = _model_dump(result) if hasattr(result, "model_dump") else result
    if not isinstance(data, dict):
        console.print(str(result))
        return

    job_id = data.get("job_id") or "(unknown)"
    proposal_id = data.get("proposal_id") or ""
    decisions = data.get("decisions") or []
    if not isinstance(decisions, list):
        decisions = []

    lines = [f"[bold green]Job:[/bold green] {job_id}"]
    if proposal_id:
        lines.append(f"[bold green]Proposal:[/bold green] {proposal_id}")
    lines.append(f"[bold green]Decisions recorded:[/bold green] {len(decisions)}")
    if decisions:
        lines.append("")
        for entry in decisions:
            if not isinstance(entry, dict):
                continue
            d_proposal = entry.get("proposal_id") or "(unknown)"
            d_decision = entry.get("decision") or "(unknown)"
            evidence = entry.get("evidence_ref") or ""
            evidence_text = f"  evidence={evidence}" if evidence else ""
            lines.append(f"  - {d_proposal}: {d_decision}{evidence_text}")
    lines.append("")
    lines.append(
        "[bold yellow]No media was rendered. Run the orchestrator's render "
        "entrypoint to produce any approved clip.[/bold yellow]"
    )

    _format_success_panel(lines, title="Shorts Review", border_style="yellow")


def _record_failure(
    failures: list[dict[str, Any]],
    *,
    proposal_id: str,
    decision: str,
    exc: BaseException,
    code: str,
) -> None:
    failures.append(
        {
            "proposal_id": proposal_id,
            "decision": decision,
            "code": getattr(exc, "code", code) or code,
            "message": str(exc),
        }
    )


def _import_product_shorts() -> Any:
    """Lazy import that surfaces a plain-language error if the module is gone.

    The orchestrator's :mod:`kinocut.product.shorts` module is a peer-shipped
    piece of the batch. If the module has not yet landed on disk, the handler
    must still be importable so ``kino --help`` lists ``shorts``. We catch the
    missing-module signal here and re-raise it as a fail-closed
    :class:`MCPVideoError` whose ``problem / cause / recovery`` envelope the
    CLI already knows how to render.
    """

    try:
        from ..product import shorts as product_shorts
    except ImportError as exc:
        raise _problem(
            "The orchestrator module kinocut.product.shorts is not yet installed on this build.",
            code="orchestrator_unavailable",
            suggested_action=(
                "Reinstall the kinocut package or upgrade to a build that "
                "ships the shorts orchestrator. The CLI surface is "
                "registered, but the orchestrator back-end is missing."
            ),
        ) from exc
    return product_shorts


def _call_review(
    review_callable: Callable[..., Any],
    plan_path: str,
    proposal_id: str,
    decision: str,
    evidence_ref: Any,
) -> Any:
    """Invoke ``shorts_review`` against one exact saved plan path."""

    try:
        return review_callable(
            plan_path,
            proposal_id,
            decision=decision,
            evidence_ref=evidence_ref,
        )
    except TypeError:
        return review_callable(plan_path, proposal_id, decision, evidence_ref)


def handle_shorts_commands(args: Any, *, use_json: bool) -> bool:
    """Dispatch the ``shorts`` subcommand.

    Returns ``True`` when ``args.command == "shorts"`` (handled or rejected),
    otherwise ``False`` so the surrounding OR-chain keeps falling through.
    """

    if getattr(args, "command", None) != "shorts":
        return False

    runner = CommandRunner(args, use_json)
    runner.register("shorts", _handle_shorts)
    return runner.dispatch()


def _handle_shorts(args: Any, use_json: bool) -> None:
    """Dispatch the explicitly selected stage, defaulting to proposal."""

    if getattr(args, "render", False):
        _render_or_package(args, use_json, stage="render")
        return
    if getattr(args, "package", False):
        _render_or_package(args, use_json, stage="package")
        return
    if getattr(args, "decisions", None) is not None:
        _review_only(args, use_json)
        return
    if not getattr(args, "input", None):
        raise _problem(
            "Proposing clips requires the source video path.",
            code="missing_input",
            suggested_action="Pass the source video path after `kino shorts`.",
        )
    _plan_only(args, use_json)


def _render_or_package(args: Any, use_json: bool, *, stage: str) -> None:
    """Run an explicit local render or package stage through the shared API."""

    job_id = getattr(args, "resume_job_id", None)
    candidate_id = getattr(args, "candidate_id", None)
    output = getattr(args, "output", None)
    output_dir = getattr(args, "output_dir", None)
    missing = [
        flag
        for flag, value in (
            ("--resume-job-id", job_id),
            ("--candidate-id", candidate_id),
            ("--output", output),
            ("--output-dir", output_dir),
        )
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise _problem(
            f"The {stage} stage requires {', '.join(missing)}.",
            code=f"missing_{stage}_input",
            suggested_action=f"Pass an explicit job, candidate, saved-plan directory, and output for --{stage}.",
        )

    product_shorts = _import_product_shorts()
    name = f"shorts_{stage}"
    callable_ = getattr(product_shorts, name, None)
    if callable_ is None:
        raise _problem(
            f"The shorts orchestrator is missing the '{name}' entrypoint.",
            code="orchestrator_unavailable",
        )
    output_kwarg = "output_path" if stage == "render" else "package_dir"
    plan_path = os.path.join(output_dir, f"{job_id}.plan.json")
    result = callable_(plan_path, candidate_id, **{output_kwarg: output})
    _out(result, use_json, lambda value: console.print(str(value)))


def _plan_only(args: Any, use_json: bool) -> None:
    """Default no-render proposal path."""

    product_shorts = _import_product_shorts()
    if not hasattr(product_shorts, "shorts_plan"):
        raise _problem(
            "The orchestrator module kinocut.product.shorts is missing the "
            "'shorts_plan' entrypoint expected by this CLI.",
            code="orchestrator_unavailable",
            suggested_action=(
                "Reinstall the kinocut.product.shorts module or upgrade to a build that exposes shorts_plan()."
            ),
        )

    kwargs = _build_plan_kwargs(args)
    result = product_shorts.shorts_plan(args.input, **kwargs)
    _out(result, use_json, _format_plan_text)


def _review_only(args: Any, use_json: bool) -> None:
    """Apply review decisions to one exact saved plan without rendering."""

    job_id = getattr(args, "resume_job_id", None)
    if not isinstance(job_id, str) or not job_id:
        raise _problem(
            "Recording decisions requires --resume-job-id so the orchestrator knows which proposal to update.",
            code="missing_resume_job_id",
            suggested_action=(
                "Re-run as `kino shorts --decisions decisions.json --resume-job-id <prior-job-id> "
                "--output-dir <saved-plan-directory>`."
            ),
        )
    output_dir = getattr(args, "output_dir", None)
    if not isinstance(output_dir, str) or not output_dir:
        raise _problem(
            "Recording decisions requires --output-dir to locate the saved plan.",
            code="missing_output_dir",
            suggested_action=(
                "Pass the same --output-dir used to create the proposal; the CLI will review "
                "<output-dir>/<job-id>.plan.json without reopening the source media."
            ),
        )

    product_shorts = _import_product_shorts()
    if not hasattr(product_shorts, "shorts_review"):
        raise _problem(
            "The orchestrator module kinocut.product.shorts is missing the "
            "'shorts_review' entrypoint expected by this CLI.",
            code="orchestrator_unavailable",
            suggested_action=(
                "Reinstall the kinocut.product.shorts module or upgrade to a build that exposes shorts_review()."
            ),
        )

    payload = _load_decisions_file(args.decisions)
    entries = _coerce_decision_entries(payload)
    plan_path = os.path.join(output_dir, f"{job_id}.plan.json")
    propose_callable = getattr(product_shorts, "shorts_propose", None)
    review_callable = product_shorts.shorts_review

    aggregated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    last_review: Any = None

    for entry in entries:
        proposal_id, decision = _validate_decision_entry(entry)
        evidence_ref = entry.get("evidence_ref") or entry.get("evidence")
        edit_payload = entry.get("edit") if isinstance(entry.get("edit"), dict) else None

        if edit_payload is not None and propose_callable is None:
            raise _problem(
                "Decisions include an 'edit' block but the orchestrator has no 'shorts_propose' entrypoint.",
                code="orchestrator_unavailable",
            )
        if edit_payload is not None:
            try:
                edit = dict(edit_payload)
                if evidence_ref is not None:
                    edit["evidence_ref"] = evidence_ref
                edited = propose_callable(plan_path, proposal_id, edit=edit)
            except Exception as exc:
                _record_failure(
                    failures,
                    proposal_id=proposal_id,
                    decision=decision,
                    exc=exc,
                    code="propose_failed",
                )
                continue
            last_review = edited
            aggregated.append(
                {
                    "proposal_id": proposal_id,
                    "decision": decision,
                    "evidence_ref": evidence_ref,
                    "result": edited,
                }
            )
            continue
        try:
            review = _call_review(review_callable, plan_path, proposal_id, decision, evidence_ref)
        except Exception as exc:
            _record_failure(
                failures,
                proposal_id=proposal_id,
                decision=decision,
                exc=exc,
                code="review_failed",
            )
            continue

        last_review = review
        aggregated.append(
            {
                "proposal_id": proposal_id,
                "decision": decision,
                "evidence_ref": evidence_ref,
                "result": review,
            }
        )

    final_payload: dict[str, Any] = {
        "job_id": job_id,
        "proposal_id": entries[0].get("proposal_id") if entries else None,
        "decisions": aggregated,
        "failures": failures,
        "plan_path": plan_path,
        "last_review": last_review,
    }

    if use_json:
        from .common import output_json

        output_json(final_payload)
        return

    _format_review_text(final_payload)
