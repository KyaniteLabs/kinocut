"""``GenerationAcceptanceSpec`` — the acceptance contract for a generation.

Design §4.2. The exact target text is stored privately: the record binds a
hash and declared region, never the raw text. Unknown fields fail on write.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from kinocut.contracts._common import (
    NormalizedRegion,
    RecordBase,
    Sha256,
    ValueObject,
)
from kinocut.contracts.defect import DefectCode, Severity


class SeverityThreshold(ValueObject):
    """A per-defect-code ceiling: findings above ``max_severity`` fail review.

    Both ends are closed enums so a threshold can never reference an unknown
    defect code or an ad-hoc severity label.
    """

    defect_code: DefectCode
    max_severity: Severity


class GenerationAcceptanceSpec(RecordBase):
    """What a generated asset must satisfy to be accepted (design §4.2)."""

    record_kind: Literal["generation_acceptance_spec"] = "generation_acceptance_spec"

    spec_id: str
    title: str
    target_formats: tuple[str, ...]
    review_policy: str
    required_subjects: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    semantic_beats: tuple[str, ...] = ()
    # Privacy: the exact target text lives only as a hash plus a declared
    # region, never as raw text on the record itself.
    exact_text_hash: Sha256 | None = None
    declared_text_region: NormalizedRegion | None = None
    required_logos: tuple[str, ...] = ()
    visual_rules: tuple[str, ...] = ()
    forbidden_defect_codes: tuple[DefectCode, ...] = ()
    severity_thresholds: tuple[SeverityThreshold, ...] = ()
    required_evidence_artifacts: tuple[str, ...] = ()
    required_review_roles: tuple[str, ...] = ()
    continuity_plan_ref: str | None = None
    cost_ceiling: float | None = None


def _requirement_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


def acceptance_requirement_ids(spec: GenerationAcceptanceSpec) -> tuple[str, ...]:
    """Return stable, category-scoped IDs for every content requirement."""

    values = (
        *(("subject", value) for value in spec.required_subjects),
        *(("action", value) for value in spec.required_actions),
        *(("beat", value) for value in spec.semantic_beats),
        *(("logo", value) for value in spec.required_logos),
    )
    result = [_requirement_id(kind, value) for kind, value in values]
    if spec.exact_text_hash is not None:
        result.append(f"exact_text:{spec.exact_text_hash}")
    return tuple(dict.fromkeys(result))
