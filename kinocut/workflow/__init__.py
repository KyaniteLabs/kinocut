"""Agent-native workflow engine (validate / plan / render / inspect).

Story 1 ships the ordered-list job-spec model and the fail-closed structural
validator (op allowlist, @ref resolution, backward-reference-only ordering,
per-op param introspection, workspace-confined path safety). Story 2 adds the
dry-run planner; Story 3 adds the sequential render executor + workflow receipt.
Story 4 adds fail-closed resume (``render_workflow(resume_receipt=...)``) and the
legacy-tolerant ``inspect_receipt`` summarizer. Story 5 adds batch variants
(``variants[].overrides`` -> N distinct outputs via ``variant=``/``all_variants=``)
and the ``keep_intermediates`` cleanup override.
"""

from __future__ import annotations

import importlib as _importlib

_EXPORTS = {
    "INVALID_WORKFLOW_PARAMS": "._errors",
    "INVALID_WORKFLOW_RECEIPT": "._errors",
    "INVALID_WORKFLOW_SPEC": "._errors",
    "INVALID_WORKFLOW_VARIANT": "._errors",
    "RESUME_SPEC_MISMATCH": "._errors",
    "RESUME_VARIANT_MISMATCH": "._errors",
    "UNKNOWN_WORKFLOW_REF": "._errors",
    "UNSAFE_WORKFLOW_SOURCE": "._errors",
    "UNSUPPORTED_WORKFLOW_OP": "._errors",
    "workflow_error": "._errors",
    "render_workflow": ".executor",
    "inspect_receipt": ".inspector",
    "read_receipt": ".inspector",
    "OP_ADAPTERS": ".ops",
    "OpAdapter": ".ops",
    "plan_workflow": ".planner",
    "WorkflowOutput": ".spec",
    "WorkflowSource": ".spec",
    "WorkflowSpec": ".spec",
    "WorkflowStep": ".spec",
    "WorkflowVariant": ".spec",
    "validate_workflow_spec": ".validator",
    "apply_variant_overrides": ".variants",
    "variant_ids": ".variants",
}
__all__ = tuple(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_importlib.import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
