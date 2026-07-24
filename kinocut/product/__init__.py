"""Product-level workflow contracts (additive).

Public surface for the long-form stream-to-shorts workflow: strict,
JSON-serialisable data contracts plus the deterministic package writer
and the persisted human-review contract.
"""

from .package import package_approved_clip
from .package_models import *  # noqa: F403
from .shorts_plan import (
    IntakeReport,
    RenderRecord,
    ReviewAction,
    ReviewDecision,
    ShortsPlan,
    ShortsPlanStatus,
    load_shorts_plan,
    save_shorts_plan,
)
from .shorts_review import resolve_approved_candidate, review_shorts_plan
from .shorts_render import render_approved_candidate

__all__ = [  # noqa: F405
    "IntakeReport",
    "PackageAsset",
    "PackageConfig",
    "PackageLineage",
    "PackagedClipResult",
    "PerformanceIdentifier",
    "PerformanceStatus",
    "RenderRecord",
    "ReviewAction",
    "ReviewDecision",
    "ShortsPackageManifest",
    "ShortsPlan",
    "ShortsPlanStatus",
    "ThumbnailSpec",
    "canonical_manifest_bytes",
    "load_shorts_plan",
    "manifest_artifact_digest",
    "package_approved_clip",
    "package_kind",
    "parse_package_manifest",
    "render_approved_candidate",
    "resolve_approved_candidate",
    "review_shorts_plan",
    "save_shorts_plan",
]
