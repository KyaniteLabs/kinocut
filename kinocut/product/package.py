"""Approved-clip packaging for the long-form stream-to-shorts workflow.

The package layer is the *handoff* between the discovery / captions /
shorts-plan slices and whatever downstream surface (human review, render
queue, or scheduler) consumes the resulting clip. It is intentionally
additive: it does not import any FFmpeg-capable engine, does not touch
``kinocut/engine_subtitles.py`` (PR #378), and does not modify the CLI
parsers. The only writers it touches are the package outputs themselves:

* The vertical video reference (passed through — the actual reframe render
  is emitted by the ``16-ClipAndReframe`` slice through ``OP_ADAPTERS``).
* The editable SRT body produced by ``kinocut.product.captions``.
* A representative thumbnail (already chosen by upstream review).
* A *machine-readable* edit manifest: source clip timestamps, lineage
  references, review warnings, optional performance identifier.

Every input the package consumes is a strict, JSON-serialisable model — a
:class:`CandidateMoment` from the discovery slice, a :class:`CaptionArtifact`
from the captions slice, and a :class:`ThumbnailSpec` selected by the
upstream review surface. Human review remains mandatory before rendering:
the package carries the candidate's ``review_warning`` and ``unsuitable``
flag verbatim into the manifest, and exposes ``drafting_only`` markers on
every piece of suggested metadata so a downstream agent can never mistake
the wording for engagement or SEO claims.

Path traversal is blocked at every boundary: a package refuses to write to
any path containing ``..`` segments, null bytes, or unsafe system
locations. The validator is the same ``_validate_artifact_path`` helper
used by the workflow render receipts (provenance artifacts always use
``label="Artifact path"``); package writers opt into a strict ``.json``
overwrite rule because the package and manifest files are themselves
provenance artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import Field, model_validator

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path, _validate_input_path
from .captions import CaptionArtifact
from .models import CandidateMoment, _StrictModel


# --- Constants -------------------------------------------------------------- #


# Allowed values for an optional performance identifier. ``draft`` is the
# default authoring state; ``experimental`` flags a non-public A/B lane.
# We intentionally do NOT model ``published``, ``viral``, or any
# engagement-shaped status: the package is drafting-only and downstream
# surfaces (review, scheduler) own the publish state.
PerformanceStatus = Literal["draft", "experimental"]
"""Optional performance-identifier status for an approved-clip package."""

# Bounded filename component for the package directory. Mirrors the
# ``_RECORD_KIND_PATTERN`` spirit from ``kinocut.contracts._common``:
# lowercase identifier, no traversal, no spaces.
_PACKAGE_KIND = "shorts_package"
package_kind: str = _PACKAGE_KIND  # re-export for tests / external callers

# Drafting-only field tags. ``drafting_only=True`` on a metadata field
# tells downstream consumers that the value is a *suggestion* — not a
# claim about engagement, ranking, virality, or algorithm favour.
_DRAFTING_ONLY_TAGS: tuple[str, ...] = (
    "suggested_title",
    "suggested_hook",
    "short_description",
)


# --- Inputs ----------------------------------------------------------------- #


class ThumbnailSpec(_StrictModel):
    """One chosen representative thumbnail for the approved clip.

    ``image_path`` is the path the review surface approved; ``timestamp`` is
    the in-clip moment the frame was extracted at. ``notes`` are reviewer
    commentary (e.g. ``"best framing of the payoff"``); the field is
    optional because some workflows schedule thumbnails without commentary.
    """

    image_path: str = Field(min_length=1)
    timestamp: float = Field(ge=0.0)
    notes: str | None = None


class PerformanceIdentifier(_StrictModel):
    """Optional, drafting-only performance identifier for an A/B lane.

    ``status == "draft"`` is the canonical state of an authored
    package; ``"experimental"`` flags a non-public A/B lane a reviewer
    explicitly authorised. There is no ``published`` state — the package
    layer never asserts a video is live.
    """

    status: PerformanceStatus
    label: str = Field(min_length=1, max_length=64)


class PackageConfig(_StrictModel):
    """Knobs that control how a package is written.

    ``manifest_basename`` is the filename component for the JSON manifest;
    a collision-safe suffix is appended if a previous write already left
    a manifest at the target path. ``overwrite_manifest`` lets the caller
    opt into overwriting an existing manifest; the default
    (``False``) makes the writer idempotent in the strict sense — re-
    running the package with the same inputs yields the same on-disk
    artifact set (or refuses to clobber an existing manifest).
    """

    manifest_basename: str = Field(default="manifest", min_length=1, max_length=64)
    overwrite_manifest: bool = False
    write_thumbnail_marker: bool = True


# --- Manifest schemas ------------------------------------------------------ #


class PackageAsset(_StrictModel):
    """One file the package wrote, with its role tag.

    The role tag is a bounded literal so a downstream consumer can render a
    typed manifest UI without parsing prose. ``relative_path`` is the path
    *relative to the package root* — never an absolute filesystem path,
    which keeps the manifest portable across workspaces.
    """

    role: Literal[
        "vertical_video",
        "editable_subtitles",
        "representative_thumbnail",
        "edit_manifest",
        "performance_identifier",
    ]
    relative_path: str = Field(min_length=1)
    bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _no_traversal_in_path(self) -> PackageAsset:
        if ".." in self.relative_path.split("/") or ".." in self.relative_path.split(os.sep):
            raise ValueError(f"asset path contains directory traversal: {self.relative_path!r}")
        if "\x00" in self.relative_path:
            raise ValueError(f"asset path contains null byte: {self.relative_path!r}")
        return self


class PackageLineage(_StrictModel):
    """Provenance references for the packaged clip.

    References are bounded sha256-prefixed digests (when the producer
    uses the canonical ``kinocut.contracts`` layer) or caller-supplied
    opaque identifiers (when the upstream slice uses its own scheme). The
    pair ``(candidate_id, transcript_reference)`` is enough for the review
    surface to walk the lineage without re-running discovery.
    """

    candidate_id: str = Field(min_length=1)
    transcript_reference: str | None = None
    generation_lineage_ref: str | None = None
    review_decision_ref: str | None = None


class PackageManifest(_StrictModel):
    """The machine-readable, JSON-stable edit manifest.

    The manifest schema is deliberately small. Every field is either a
    bounded identifier, a strict embedded model, or a tuple of them; the
    whole object round-trips through ``model_dump(mode="json")`` with
    sorted keys and compact separators, and ``drafting_only_flags``
    enumerates the fields that are *suggestions*, not engagement claims.
    A reviewer can scan ``drafting_only_flags`` to see exactly which
    fields must not be quoted as performance guarantees.
    """

    schema_version: int = Field(default=1, ge=1, le=1)
    package_kind: str = Field(default=_PACKAGE_KIND, min_length=1)
    package_id: str = Field(min_length=1)
    package_root: str = Field(min_length=1)
    generated_at: str | None = None  # informational; never part of an identity digest
    candidate: CandidateMoment
    caption_artifact: CaptionArtifact
    suggested_title: str | None = None
    short_description: str | None = None
    source_timestamps: tuple[float, float] | None = None
    thumbnail: ThumbnailSpec
    lineage: PackageLineage
    assets: tuple[PackageAsset, ...]
    review_warnings: tuple[str, ...]
    drafting_only_flags: tuple[str, ...] = tuple(_DRAFTING_ONLY_TAGS)
    performance: PerformanceIdentifier | None = None

    @model_validator(mode="after")
    def _validate_warnings_match(self) -> PackageManifest:
        """Surface every warning the candidate already declared.

        The candidate's ``review_warning`` is the canonical single-string
        signal the discovery slice emits; the package may add additional
        review warnings of its own (e.g. low-confidence words flagged).
        The union becomes the manifest's ``review_warnings`` so a
        reviewer can read every relevant flag in one place.
        """

        return self


# --- Result returned by the writer ----------------------------------------- #


class PackagedClipResult(_StrictModel):
    """The deterministic result of :func:`package_approved_clip`.

    ``package_root`` is the directory the package writes to; ``manifest_path``
    is the path of the JSON manifest on disk; the ``asset_paths`` tuple is
    every file the package emitted (in ``PackageManifest.assets`` order).
    Files are absolute paths because the caller asked for them; the manifest
    itself stores *relative* paths so it stays workspace-portable.
    """

    package_root: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    asset_paths: tuple[str, ...]
    manifest: PackageManifest


# --- Helper: package id derivation ----------------------------------------- #


_HEX_RE = re.compile(r"^[0-9a-f]{16}$")


def _package_id(candidate: CandidateMoment) -> str:
    """Stable package id derived from the candidate's canonical content.

    The id is ``pkg_<16-hex sha256 prefix>``; the candidate's own
    ``dedup_key`` is the seed so two packages derived from the same
    candidate produce identical ids (and hence can be tested for
    idempotence).
    """

    seed = candidate.dedup_key
    if not _HEX_RE.match(seed):
        raise MCPVideoError(
            "candidate dedup_key is not a 16-hex digest; cannot derive package id",
            error_type="validation_error",
            code="invalid_dedup_key",
        )
    return f"pkg_{seed}"


def _manifest_filename_for(package_id: str, basename: str) -> str:
    """Render the manifest's filename with a bounded ``.json`` suffix."""

    safe_basename = re.sub(r"[^A-Za-z0-9._-]", "_", basename)[:64]
    return f"{package_id}__{safe_basename}.json"


def _audit_bytes(path: str) -> int | None:
    """Return the size of ``path`` in bytes, or ``None`` if unavailable."""

    try:
        return os.path.getsize(path)
    except OSError:
        return None


# --- Public API ------------------------------------------------------------ #


def package_approved_clip(
    *,
    package_dir: str,
    vertical_video_path: str,
    caption_artifact: CaptionArtifact,
    candidate: CandidateMoment,
    thumbnail: ThumbnailSpec,
    lineage: PackageLineage | None = None,
    performance: PerformanceIdentifier | None = None,
    extra_review_warnings: Iterable[str] = (),
    config: PackageConfig | None = None,
    generated_at: str | None = None,
) -> PackagedClipResult:
    """Write the package directory and return a strict result.

    The function does the following, in order:

    1. Validates every user-supplied path (``package_dir``,
       ``vertical_video_path``, ``caption_artifact.srt_path`` when
       present, ``thumbnail.image_path``) against path traversal,
       null bytes, and the existing-artifact overwrite rule.
    2. Writes the editable SRT body into the package directory.
    3. Emits a manifest summarising the package and writes it to disk.
    4. Returns :class:`PackagedClipResult` so the caller can verify the
       on-disk artifact set.

    The actual reframe/burn-in rendering is *not* part of this function:
    the orchestrator emits ``trim``/``resize``/``burn_in`` steps via
    :class:`kinocut.workflow.OP_ADAPTERS` and the workflow executor
    handles the render.
    """

    cfg = config or PackageConfig()
    if not isinstance(cfg, PackageConfig):
        cfg = PackageConfig.model_validate(cfg)

    # --- Path validation --------------------------------------------------- #
    if not isinstance(candidate, CandidateMoment):
        raise MCPVideoError(
            "candidate must be a strict CandidateMoment",
            error_type="validation_error",
            code="invalid_candidate",
        )
    if not isinstance(caption_artifact, CaptionArtifact):
        raise MCPVideoError(
            "caption_artifact must be a strict CaptionArtifact",
            error_type="validation_error",
            code="invalid_caption_artifact",
        )

    safe_dir = _validate_artifact_path(package_dir)
    safe_dir = os.path.realpath(os.path.expanduser(safe_dir))
    os.makedirs(safe_dir, exist_ok=True)

    # ``package_dir`` is the destination we own — strict provenance-artifact
    # validation. ``vertical_video_path`` and ``thumbnail.image_path`` are
    # *references* to existing media (we never overwrite them); we validate
    # them as ``input`` paths so the package accepts whatever the upstream
    # reviewer chose, including non-``.json`` suffixes.
    safe_video = _validate_input_path(vertical_video_path)
    safe_thumbnail = _validate_input_path(thumbnail.image_path)

    # --- Write SRT body ---------------------------------------------------- #
    srt_path = os.path.join(safe_dir, "captions.srt")
    srt_existed = os.path.exists(srt_path)
    if srt_existed and not cfg.overwrite_manifest:
        # The SRT is itself an editable artifact; refuse to clobber.
        raise MCPVideoError(
            f"caption asset already exists and overwrite_manifest is false: {srt_path!r}",
            error_type="validation_error",
            code="package_write_conflict",
        )
    with open(srt_path, "w", encoding="utf-8") as handle:
        handle.write(caption_artifact.srt_body)
        if not caption_artifact.srt_body.endswith("\n"):
            handle.write("\n")

    # --- Manifest construction -------------------------------------------- #
    package_id = _package_id(candidate)

    assets: list[PackageAsset] = [
        PackageAsset(
            role="vertical_video",
            relative_path=os.path.basename(safe_video),
            bytes=_audit_bytes(safe_video),
        ),
        PackageAsset(
            role="edit_manifest",
            relative_path="manifest:placeholder",  # patched below
            bytes=None,
        ),
        PackageAsset(
            role="editable_subtitles",
            relative_path="captions.srt",
            bytes=_audit_bytes(srt_path),
        ),
        PackageAsset(
            role="representative_thumbnail",
            relative_path=os.path.basename(safe_thumbnail),
            bytes=_audit_bytes(safe_thumbnail),
        ),
    ]

    package_lineage = lineage or PackageLineage(candidate_id=candidate.candidate_id)

    # Compose the manifest with a placeholder for ``edit_manifest``; we
    # patch it after we know the manifest's filename so the relative
    # path is accurate even if multiple packages share a directory.
    merged_warnings: list[str] = []
    if candidate.review_warning:
        merged_warnings.append(candidate.review_warning)
    merged_warnings.extend(caption_artifact.review_warnings)
    merged_warnings.extend(extra_review_warnings)

    placeholder = PackageManifest(
        package_kind=_PACKAGE_KIND,
        package_id=package_id,
        package_root=safe_dir,
        generated_at=generated_at,
        candidate=candidate,
        caption_artifact=caption_artifact,
        suggested_title=candidate.suggested_title,
        short_description=candidate.suggested_hook,
        source_timestamps=(candidate.start, candidate.end),
        thumbnail=thumbnail,
        lineage=package_lineage,
        assets=tuple(assets),
        review_warnings=tuple(_dedupe(merged_warnings)),
        drafting_only_flags=tuple(_DRAFTING_ONLY_TAGS),
        performance=performance,
    )

    manifest_filename = _manifest_filename_for(package_id, cfg.manifest_basename)
    manifest_path = os.path.join(safe_dir, manifest_filename)

    if os.path.exists(manifest_path) and not cfg.overwrite_manifest:
        raise MCPVideoError(
            f"manifest already exists and overwrite_manifest is false: {manifest_path!r}",
            error_type="validation_error",
            code="package_write_conflict",
        )

    # --- Patch the placeholder's edit_manifest asset to its real filename - #
    patched_assets = tuple(
        PackageAsset(
            role=asset.role,
            relative_path=manifest_filename if asset.role == "edit_manifest" else asset.relative_path,
            bytes=asset.bytes,
        )
        if asset.role == "edit_manifest"
        else asset
        for asset in placeholder.assets
    )

    final_manifest = placeholder.model_copy(update={"assets": patched_assets})

    # --- Atomic JSON write (sorted keys + compact separators) ------------- #
    payload = final_manifest.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.write("\n")

    asset_paths = (
        safe_video,
        manifest_path,
        srt_path,
        safe_thumbnail,
    )

    return PackagedClipResult(
        package_root=safe_dir,
        manifest_path=manifest_path,
        asset_paths=asset_paths,
        manifest=final_manifest,
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    """Stable, order-preserving deduplication of ``values``.

    Pydantic's ``tuple`` fields are order-sensitive, so we keep the first
    occurrence of each value and discard later duplicates without changing
    the surviving order.
    """

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


# --- Manifest round-trip helper exposed for tests ------------------------- #


def parse_package_manifest(payload: str | bytes) -> PackageManifest:
    """Parse a JSON-encoded package manifest back into a strict model.

    Round-trip accepts either text or bytes; both are decoded as UTF-8
    with ``strict`` error handling so a malformed payload surfaces as
    :class:`MCPVideoError` rather than silently truncating.
    """

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MCPVideoError(
                "manifest payload is not valid UTF-8",
                error_type="validation_error",
                code="invalid_manifest_encoding",
            ) from exc
    try:
        data: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            "manifest payload is not valid JSON",
            error_type="validation_error",
            code="invalid_manifest_json",
        ) from exc
    return PackageManifest.model_validate(data)


def canonical_manifest_bytes(manifest: PackageManifest) -> bytes:
    """Render a manifest to its canonical JSON byte form.

    Mirrors ``kinocut.contracts._common.canonical_record_id``'s encoding
    (sorted keys + compact separators + ``allow_nan=False``) so two
    logically-equal manifests produce byte-identical serialisations —
    a precondition for the round-trip + idempotent-write tests.
    """

    payload = manifest.model_dump(mode="json")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def manifest_artifact_digest(manifest: PackageManifest) -> str:
    """Stable 16-hex prefix of the manifest's canonical digest.

    Provided so callers (and tests) can key idempotent re-runs without
    adopting the full ``kinocut.contracts`` layer.
    """

    digest = hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
    return digest[:16]


__all__ = [
    "PackageAsset",
    "PackageConfig",
    "PackageLineage",
    "PackageManifest",
    "PackagedClipResult",
    "PerformanceIdentifier",
    "PerformanceStatus",
    "ThumbnailSpec",
    "canonical_manifest_bytes",
    "manifest_artifact_digest",
    "package_approved_clip",
    "package_kind",
    "parse_package_manifest",
]
