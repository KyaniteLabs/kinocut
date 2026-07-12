"""Canonical AI-video record contracts (Wave 0 foundation).

Stable public surface for the shared record base, typed ids, canonical
hashing, contract error helpers, and the domain record models (acceptance,
asset, verdict, defect, protection, review, learning).
"""

from __future__ import annotations

from kinocut.contracts._common import (
    AssetId,
    NormalizedRegion,
    RecordBase,
    Sha256,
    ValueObject,
    canonical_record_id,
)
from kinocut.contracts._errors import (
    INVALID_RECORD,
    RECORD_SUPERSESSION_CYCLE,
    STALE_APPROVAL_FINGERPRINT,
    UNKNOWN_RECORD_FIELD,
    contract_error,
)
from kinocut.contracts.acceptance import (
    GenerationAcceptanceSpec,
    SeverityThreshold,
)
from kinocut.contracts.adapter import parse_record_json, validate_record
from kinocut.contracts.capability import (
    AvailabilityState,
    CapabilityReport,
    NextAction,
    SurfaceAvailability,
)
from kinocut.contracts.asset import (
    AssetRecord,
    GenerationLineage,
    MediaKind,
    UsageRightsStatus,
)
from kinocut.contracts.defect import (
    TAXONOMY_VERSION,
    DefectCode,
    DefectFinding,
    DefectStatus,
    Measurement,
    Severity,
)
from kinocut.contracts.learning import (
    CostConfidence,
    CostEvent,
    ParameterSlot,
    PromptOutcome,
    UsageEvent,
    WorkflowRecipe,
)
from kinocut.contracts.protection import (
    DurationPolicy,
    ElementType,
    ProtectedElement,
)
from kinocut.contracts.receipt_ai_video import (
    AiVideoReceiptSection,
    OrderedInput,
    PreservationProof,
    PreservationVerdict,
    Transformation,
)
from kinocut.contracts.review import (
    ApprovalState,
    ApprovalStateValue,
    DecisionType,
    IntegrityResult,
    KnownLimitation,
    ReviewDecision,
)
from kinocut.contracts.verdict import ClipVerdict, Disposition

__all__ = [
    "INVALID_RECORD",
    "RECORD_SUPERSESSION_CYCLE",
    "STALE_APPROVAL_FINGERPRINT",
    "TAXONOMY_VERSION",
    "UNKNOWN_RECORD_FIELD",
    "AiVideoReceiptSection",
    "ApprovalState",
    "ApprovalStateValue",
    "AssetId",
    "AssetRecord",
    "AvailabilityState",
    "CapabilityReport",
    "ClipVerdict",
    "CostConfidence",
    "CostEvent",
    "DecisionType",
    "DefectCode",
    "DefectFinding",
    "DefectStatus",
    "Disposition",
    "DurationPolicy",
    "ElementType",
    "GenerationAcceptanceSpec",
    "GenerationLineage",
    "IntegrityResult",
    "KnownLimitation",
    "Measurement",
    "MediaKind",
    "NextAction",
    "NormalizedRegion",
    "OrderedInput",
    "ParameterSlot",
    "PreservationProof",
    "PreservationVerdict",
    "PromptOutcome",
    "ProtectedElement",
    "RecordBase",
    "ReviewDecision",
    "Severity",
    "SeverityThreshold",
    "Sha256",
    "SurfaceAvailability",
    "Transformation",
    "UsageEvent",
    "UsageRightsStatus",
    "ValueObject",
    "WorkflowRecipe",
    "canonical_record_id",
    "contract_error",
    "parse_record_json",
    "validate_record",
]
