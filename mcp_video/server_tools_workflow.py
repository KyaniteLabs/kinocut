"""Workflow-engine MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp
from .workflow import inspect_receipt, plan_workflow, render_workflow, validate_workflow_spec


@mcp.tool()
@_safe_tool
def video_workflow_validate(spec_path: str) -> dict[str, Any]:
    """Validate an agent workflow job-spec without rendering any media.

    Runs the fail-closed structural validator over the JSON job-spec at
    ``spec_path``: op allowlist (probe|trim|resize|convert|merge|add_text),
    symbolic ``@ref`` resolution (@sources.<id>, @work/<name>, @outputs.<id>),
    backward-reference-only ordering (a step may reference @work outputs from
    strictly-earlier steps only), per-op param introspection, and
    workspace-confined path safety (absolute paths and ../ / symlink escapes
    fail closed).

    Returns a structured verdict (``{"valid": true, ...}``) on success. On any
    structural violation it fails closed with a specific error ``code``
    (``invalid_workflow_spec``, ``unknown_workflow_ref``,
    ``unsupported_workflow_op``, ``unsafe_workflow_source``,
    ``invalid_workflow_params``).

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
    """
    return _result(validate_workflow_spec(spec_path))


@mcp.tool()
@_safe_tool
def video_workflow_plan(
    spec_path: str, save_plan: str | None = None, variant: str | None = None
) -> dict[str, Any]:
    """Produce a no-render plan for an agent workflow job-spec.

    Validates the spec first (fail-closed) and then builds a dry-run plan
    artifact WITHOUT rendering any media: the ordered operation graph, per-source
    ffprobe results (duration/resolution/codec) and sha256 content hashes where
    the source file exists, declared output intents, a variant-expansion summary,
    tool + FFmpeg versions, and warnings for runtime concerns that are not
    structural errors (e.g. a source file that does not exist yet). The only file
    written is the optional plan JSON at ``save_plan``; paths inside the artifact
    are workspace-relative.

    Pass ``variant`` to plan a single named batch variant: the plan reflects that
    variant's EFFECTIVE (post-override) steps and auto-named output paths and
    records ``workflow.variant``. An unknown variant or malformed override fails
    closed (``invalid_workflow_variant``).

    Returns the plan artifact on success. On a structurally invalid spec it fails
    closed with a specific error ``code`` (same codes as ``video_workflow_validate``).

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
        save_plan: Optional path to write the plan artifact as JSON.
        variant: Optional declared variant id to plan its effective steps.
    """
    return _result(plan_workflow(spec_path, save_plan, variant))


@mcp.tool()
@_safe_tool
def video_workflow_render(
    spec_path: str,
    resume_receipt: str | None = None,
    save_receipt: str | None = None,
    keep_intermediates: bool = False,
    variant: str | None = None,
    all_variants: bool = False,
    save_receipt_dir: str | None = None,
) -> dict[str, Any]:
    """Execute an agent workflow job-spec and return a provenance receipt.

    Validates the spec first (fail-closed), then runs each allowlisted op
    (probe|trim|resize|convert|merge|add_text) SEQUENTIALLY in spec order via the
    backing engine functions. Intermediates are written to a per-run ``@work``
    directory unique to this invocation and cleaned on success (kept on failure);
    final media lands at the declared ``@outputs`` paths.

    Batch variants: pass ``variant=<id>`` to render one declared variant (its
    overrides patch the shared steps/outputs, and the single ``@outputs`` path is
    auto-named with the variant id so N variants emit N distinct outputs); the
    receipt records ``workflow.variant``. Pass ``all_variants=True`` to render EVERY
    declared variant in turn and return a ``workflow_batch`` summary (one receipt
    per variant, each into its own ``@work`` dir); use ``save_receipt_dir`` to also
    write each variant's receipt to ``<dir>/<variant>.json``. ``variant`` and
    ``all_variants`` are mutually exclusive. Pass ``keep_intermediates=True`` to
    retain ``@work`` intermediates even on success (recorded as the
    ``keep-intermediates`` cleanup policy).

    Pass ``resume_receipt`` (a prior render receipt from a job that failed with its
    intermediates kept) to RESUME: the current spec_hash must equal the receipt's
    (else fail-closed ``resume_spec_mismatch``) AND, for a variant, the receipt's
    variant must match (else ``resume_variant_mismatch``); each step whose recorded
    status is ``completed`` AND whose recorded input hashes still match AND whose
    recorded output file still exists and re-hashes to the recorded hash is SKIPPED,
    and the first step failing any check plus everything after it re-runs.

    Returns a workflow receipt (``receipt_kind: "workflow"``) capturing tool +
    FFmpeg versions, the spec hash, per-source probes/hashes, per-step status with
    real sha256 hashes of every consumed input and produced output, the cleanup
    manifest, and the determinism-scope caveat. On the first failing step it fails
    closed: the failure is recorded on the receipt (still written to
    ``save_receipt`` when given) and surfaced as a structured error.

    Args:
        spec_path: Absolute path to the workflow job-spec JSON file.
        resume_receipt: Optional path to a prior render receipt to resume from.
        save_receipt: Optional path to write the workflow receipt as JSON.
        keep_intermediates: Retain @work intermediates even on success.
        variant: Optional declared variant id to render a single variant.
        all_variants: Render every declared variant and return a batch summary.
        save_receipt_dir: With all_variants, directory for per-variant receipts.
    """
    return _result(
        render_workflow(
            spec_path,
            resume_receipt,
            save_receipt,
            keep_intermediates,
            variant,
            all_variants,
            save_receipt_dir,
        )
    )


@mcp.tool()
@_safe_tool
def video_workflow_inspect(receipt_path: str) -> dict[str, Any]:
    """Summarize any receipt this project emits, with a read-only integrity check.

    Reads a workflow render receipt, a dry-run ``workflow_plan`` artifact, or a
    ``layer_plan`` receipt (v1 legacy with NO ``receipt_kind`` field, or v2) at
    ``receipt_path`` and returns a NORMALIZED inspection: the kind (inferred from
    the ``tool`` field when ``receipt_kind`` is absent, per legacy tolerance),
    schema_version, tool, versions, a status summary (per-step statuses, failed
    step + error if any), a hash presence/integrity report (which recorded
    source/output hashes still match the bytes on disk NOW — a read-only re-check),
    outputs, warnings, cleanup state, plus human-review pointers and known
    limitations.

    Nothing is rendered or modified. A malformed/unreadable receipt fails closed
    with ``invalid_workflow_receipt``.

    Args:
        receipt_path: Absolute path to the receipt JSON file to inspect.
    """
    return _result(inspect_receipt(receipt_path))
