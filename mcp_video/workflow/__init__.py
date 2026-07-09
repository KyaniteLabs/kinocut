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

from ._errors import (
    INVALID_WORKFLOW_PARAMS as INVALID_WORKFLOW_PARAMS,
    INVALID_WORKFLOW_RECEIPT as INVALID_WORKFLOW_RECEIPT,
    INVALID_WORKFLOW_SPEC as INVALID_WORKFLOW_SPEC,
    INVALID_WORKFLOW_VARIANT as INVALID_WORKFLOW_VARIANT,
    RESUME_SPEC_MISMATCH as RESUME_SPEC_MISMATCH,
    RESUME_VARIANT_MISMATCH as RESUME_VARIANT_MISMATCH,
    UNKNOWN_WORKFLOW_REF as UNKNOWN_WORKFLOW_REF,
    UNSAFE_WORKFLOW_SOURCE as UNSAFE_WORKFLOW_SOURCE,
    UNSUPPORTED_WORKFLOW_OP as UNSUPPORTED_WORKFLOW_OP,
    workflow_error as workflow_error,
)
from .executor import render_workflow as render_workflow
from .inspector import (
    inspect_receipt as inspect_receipt,
    read_receipt as read_receipt,
)
from .ops import (
    OP_ADAPTERS as OP_ADAPTERS,
    OpAdapter as OpAdapter,
)
from .planner import plan_workflow as plan_workflow
from .spec import (
    WorkflowOutput as WorkflowOutput,
    WorkflowSource as WorkflowSource,
    WorkflowSpec as WorkflowSpec,
    WorkflowStep as WorkflowStep,
    WorkflowVariant as WorkflowVariant,
)
from .validator import validate_workflow_spec as validate_workflow_spec
from .variants import (
    apply_variant_overrides as apply_variant_overrides,
    variant_ids as variant_ids,
)
