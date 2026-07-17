"""Phase-1 internal compatibility bridge for closed timeline operations.

Compiles closed kinds (trim/merge/burn_in/reframe/crop/silence_cut) into durable ``sha256:<hex>``
ids without a timeline IR/DAG or public-surface change (analysis ops stay CAS producers).
``synthesize_workflow_spec`` lowers the renderable subset (trim/merge/reframe/silence_cut plus
crop/burn_in over the agreed workflow op names), reporting only the genuinely unrenderable kinds.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.trusted_execution import CASManifestRecord, EditRevisionRecord
from kinocut.projectstore.cas import resolve_blob
from kinocut.projectstore.edit_projects import append_revision, get_edit_project
from kinocut.projectstore.render_jobs import job_spec_path
from kinocut.projectstore.store import Project, read_records

__all__ = [
    "CAS_PRODUCER_KINDS",
    "CLOSED_KINDS",
    "NormalizedOperation",
    "WorkflowSpecSynthesis",
    "compile_operations",
    "compile_repurpose_slice",
    "materialize_workflow_sources",
    "synthesize_workflow_spec",
]

#: Closed timeline mutation kinds this bridge compiles into durable operation ids.
CLOSED_KINDS: tuple[str, ...] = ("trim", "merge", "burn_in", "reframe", "crop", "silence_cut")
#: Analysis operations that remain CAS producers and may never be compiled here.
CAS_PRODUCER_KINDS: frozenset[str] = frozenset({"transcribe", "highlight_detect", "scene_detect"})
_RENDERABLE_KINDS: frozenset[str] = frozenset({"trim", "merge", "reframe", "silence_cut", "crop", "burn_in"})
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SOURCE_PREFIX = "@sources."
_WORK_PREFIX = "@work/"
_OUTPUT_PREFIX = "@outputs."
_SOURCES_DIR = "sources"  # opaque job-relative directory for materialized source blobs
_SOURCE_ID_RE = re.compile(r"^src[0-9]+$")  # only synthesis-generated src<digits> ids may materialize
_CHUNK = 1 << 20  # streaming chunk for hard-linked target integrity re-checks
#: media_type -> declared source path extension (primary determinant of a source's suffix).
_MEDIA_TYPE_EXT: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "application/x-subrip": ".srt",
    "text/vtt": ".vtt",
    "text/x-ssa": ".ass",
    "application/x-ass": ".ass",
}
_DEFAULT_VIDEO_EXT = ".mp4"  # consuming-op fallback when a video-role source has no mapped media_type
_DEFAULT_SUBTITLE_EXT = ".srt"  # consuming-op fallback when a subtitle-role source has no mapped media_type

# Per-kind descriptor key allowlist (mirrors extra="forbid"); typos never silently change an operation id.
_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "trim": frozenset({"kind", "source", "start", "end"}),
    "merge": frozenset({"kind", "sources"}),
    "reframe": frozenset({"kind", "source", "width", "height"}),
    "crop": frozenset({"kind", "source", "x", "y", "width", "height", "crop_percent"}),
    "burn_in": frozenset({"kind", "source", "subtitle"}),
    "silence_cut": frozenset({"kind", "source", "keep_segments"}),
}


@dataclass(frozen=True)
class NormalizedOperation:
    """A fail-closed-validated, canonical-form operation ready for id synthesis or lowering."""

    kind: str
    sources: tuple[str, ...]  # ordered sha256 digests of every content-addressed input
    params: dict[str, Any]  # normalized canonical params (key order is irrelevant to the id)
    order: int  # position in the slice; binds ordering into the durable id


@dataclass(frozen=True)
class WorkflowSpecSynthesis:
    """A lowered validator-safe workflow spec and the compiled kinds it could not render."""

    spec: dict[str, Any]
    unrendered_kinds: tuple[str, ...]
    source_digests: dict[str, str]  # source_id -> verified sha256 digest (for job-dir materialization)


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise contract_error(f"{label} must be a sha256 digest", INVALID_RECORD)
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise contract_error(f"{label} must be a nonnegative finite number", INVALID_RECORD)
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise contract_error(f"{label} must be a nonnegative finite number", INVALID_RECORD)
    return number


def _int(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise contract_error(f"{label} must be an integer >= {minimum}", INVALID_RECORD)
    return value


def _field(descriptor: Mapping[str, Any], key: str) -> Any:
    if key not in descriptor:
        raise contract_error(f"operation descriptor missing required field {key!r}", INVALID_RECORD)
    return descriptor[key]


def _keep_segments(descriptor: Mapping[str, Any]) -> list[list[float]]:
    raw = _field(descriptor, "keep_segments")
    if not isinstance(raw, (list, tuple)) or not raw:
        raise contract_error("silence_cut requires a non-empty keep_segments list", INVALID_RECORD)
    segments: list[list[float]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise contract_error(f"silence_cut keep_segments[{index}] must be a [start, end] pair", INVALID_RECORD)
        start = _number(entry[0], f"silence_cut keep_segments[{index}] start")
        end = _number(entry[1], f"silence_cut keep_segments[{index}] end")
        if end <= start:
            raise contract_error(f"silence_cut keep_segments[{index}] end must be greater than start", INVALID_RECORD)
        segments.append([start, end])
    for previous, current in itertools.pairwise(segments):
        if current[0] < previous[1]:
            raise contract_error("silence_cut keep_segments must be ordered and non-overlapping", INVALID_RECORD)
    return segments


def _crop_percent(value: Any, label: str) -> float:
    """Normalize a centered crop percentage (mirrors engine ``crop_percent``: 0 < p <= 100)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise contract_error(f"{label} must be a finite number in (0, 100]", INVALID_RECORD)
    number = float(value)
    if not math.isfinite(number) or not (0.0 < number <= 100.0):
        raise contract_error(f"{label} must be a finite number in (0, 100]", INVALID_RECORD)
    return number


def _cas_media_type(project: Project, digest: str) -> str | None:
    """Return the stored CAS ``media_type`` for ``digest`` (None when absent/unverifiable)."""
    matches = [
        record
        for record in read_records(project, "cas_manifest")
        if isinstance(record, CASManifestRecord) and record.digest == digest
    ]
    if len(matches) != 1:
        return None
    return matches[0].media_type


def _source_extension(project: Project, digest: str, *, subtitle_role: bool) -> str:
    """Deterministic source suffix: CAS ``media_type`` primary, consuming-op role as fallback.

    Subtitle suffixes (.srt/.vtt/.ass) round-trip from a mapped subtitle media type; a
    media-type-less source falls back to its consuming role (subtitle track vs. video).
    """
    media_type = _cas_media_type(project, digest)
    if media_type is not None:
        mapped = _MEDIA_TYPE_EXT.get(media_type)
        if mapped is not None:
            return mapped
    return _DEFAULT_SUBTITLE_EXT if subtitle_role else _DEFAULT_VIDEO_EXT


def _normalize_operation(descriptor: Any, order: int) -> NormalizedOperation:
    if not isinstance(descriptor, Mapping):
        raise contract_error("operation descriptor must be a mapping", INVALID_RECORD)
    kind = descriptor.get("kind")
    if not isinstance(kind, str):
        raise contract_error("operation 'kind' must be a string", INVALID_RECORD)
    if kind in CAS_PRODUCER_KINDS:
        raise contract_error(f"operation kind {kind!r} is a CAS producer and cannot be compiled", INVALID_RECORD)
    if kind not in _ALLOWED_KEYS:
        raise contract_error(f"unknown operation kind: {kind!r}", INVALID_RECORD)
    extra = sorted(set(descriptor) - _ALLOWED_KEYS[kind])
    if extra:
        raise contract_error(f"{kind} descriptor has unknown key(s): {extra}", INVALID_RECORD)
    if kind == "merge":
        raw = _field(descriptor, "sources")
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise contract_error("merge requires at least two ordered source digests", INVALID_RECORD)
        sources: tuple[str, ...] = tuple(_require_digest(s, "merge source") for s in raw)
        params: dict[str, Any] = {}
    elif kind == "burn_in":
        sources = (
            _require_digest(_field(descriptor, "source"), "burn_in source"),
            _require_digest(_field(descriptor, "subtitle"), "burn_in subtitle"),
        )
        params = {}  # identified by its video + subtitle inputs; rendering is out of scope
    else:
        source = _require_digest(_field(descriptor, "source"), f"{kind} source")
        sources = (source,)
        if kind == "trim":
            start = _number(_field(descriptor, "start"), "trim start")
            end = _number(_field(descriptor, "end"), "trim end")
            if end <= start:
                raise contract_error("trim end must be greater than start", INVALID_RECORD)
            params = {"start": start, "end": end}
        elif kind == "reframe":
            params = {
                "width": _int(_field(descriptor, "width"), "reframe width", minimum=1),
                "height": _int(_field(descriptor, "height"), "reframe height", minimum=1),
            }
        elif kind == "crop":
            # Exactly one mode: width+height (x/y optional, centered when omitted) OR crop_percent.
            has_percent = "crop_percent" in descriptor
            has_pixels = "width" in descriptor or "height" in descriptor
            if has_percent and has_pixels:
                raise contract_error("crop: use either width+height or crop_percent, not both", INVALID_RECORD)
            if has_percent:
                if "x" in descriptor or "y" in descriptor:
                    raise contract_error("crop: x/y are only valid with the width+height mode", INVALID_RECORD)
                params = {"crop_percent": _crop_percent(_field(descriptor, "crop_percent"), "crop crop_percent")}
            elif "width" in descriptor and "height" in descriptor:
                params = {
                    "width": _int(descriptor["width"], "crop width", minimum=1),
                    "height": _int(descriptor["height"], "crop height", minimum=1),
                }
                if "x" in descriptor:
                    params["x"] = _int(descriptor["x"], "crop x", minimum=0)
                if "y" in descriptor:
                    params["y"] = _int(descriptor["y"], "crop y", minimum=0)
            else:
                raise contract_error("crop requires width+height or crop_percent", INVALID_RECORD)
        else:  # silence_cut
            params = {"keep_segments": _keep_segments(descriptor)}
    return NormalizedOperation(kind=kind, sources=sources, params=params, order=order)


def _operation_id(operation: NormalizedOperation) -> str:
    payload = {
        "kind": operation.kind,
        "sources": list(operation.sources),
        "params": operation.params,
        "order": operation.order,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def compile_operations(operations: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Validate every descriptor fail-closed; return ordered durable ``sha256:<hex>`` ids.

    Each id covers kind, ordered source digests, normalized params, and position,
    so equal slices share ids while reordering or param changes differ.
    """
    return tuple(_operation_id(_normalize_operation(descriptor, index)) for index, descriptor in enumerate(operations))


def compile_repurpose_slice(
    project: Project,
    edit_project_id: str,
    operations: Iterable[Mapping[str, Any]],
    base_revision_id: str | None = None,
) -> EditRevisionRecord:
    """Compile ``operations`` to ordered ids and append one linear revision.

    Delegates to :func:`append_revision`: head advances by one, a ``revision.created``
    event fires, and a stale ``base_revision_id`` fails closed (no new public surface).
    """
    operation_ids = compile_operations(operations)
    return append_revision(project, edit_project_id, operation_ids=operation_ids, base_revision_id=base_revision_id)


def _source_ref(digest: str, source_ids: dict[str, str]) -> str:
    return _SOURCE_PREFIX + source_ids[digest]


def _step(step_id: str, op: str, inputs: dict[str, Any], params: dict[str, Any], output: str) -> dict[str, Any]:
    return {"id": step_id, "op": op, "inputs": inputs, "params": params, "output": output}


def _lower_operation(
    op: NormalizedOperation, source_ids: dict[str, str], output_id: str, steps: list[dict[str, Any]]
) -> None:
    """Append the validator-safe workflow steps for one renderable operation."""
    out = _OUTPUT_PREFIX + output_id
    if op.kind == "merge":
        steps.append(
            _step(f"merge_{output_id}", "merge", {"srcs": [_source_ref(d, source_ids) for d in op.sources]}, {}, out)
        )
        return
    if op.kind == "burn_in":  # burn_in -> multi-source video + subtitle over the agreed op name
        video_ref = _source_ref(op.sources[0], source_ids)
        subtitle_ref = _source_ref(op.sources[1], source_ids)
        steps.append(_step(f"burn_in_{output_id}", "burn_in", {"srcs": [video_ref, subtitle_ref]}, {}, out))
        return
    src = _source_ref(op.sources[0], source_ids)
    if op.kind == "trim":
        steps.append(
            _step(
                f"trim_{output_id}", "trim", {"src": src}, {"start": op.params["start"], "end": op.params["end"]}, out
            )
        )
    elif op.kind == "reframe":  # reframe -> resize
        steps.append(
            _step(
                f"resize_{output_id}",
                "resize",
                {"src": src},
                {"width": op.params["width"], "height": op.params["height"]},
                out,
            )
        )
    elif op.kind == "crop":  # crop -> agreed "crop" op; canonical params pass straight through
        steps.append(_step(f"crop_{output_id}", "crop", {"src": src}, dict(op.params), out))
    else:  # silence_cut -> ordered trim work steps + merge
        names: list[str] = []
        for index, (start, end) in enumerate(op.params["keep_segments"]):
            name = f"seg_{output_id}_{index}"
            names.append(name)
            steps.append(
                _step(
                    f"silence_trim_{output_id}_{index}",
                    "trim",
                    {"src": src},
                    {"start": start, "end": end},
                    _WORK_PREFIX + name,
                )
            )
        steps.append(_step(f"silence_merge_{output_id}", "merge", {"srcs": [_WORK_PREFIX + n for n in names]}, {}, out))


def synthesize_workflow_spec(
    project: Project,
    edit_project_id: str,
    operations: Iterable[Mapping[str, Any]],
    base_revision_id: str | None = None,
) -> WorkflowSpecSynthesis:
    """Lower the renderable subset of ``operations`` to a validator-safe workflow spec.

    trim/merge/reframe(->resize)/silence_cut(->trim+merge), crop and burn_in become workspace-relative
    steps over verified CAS sources; each source path's extension is derived from its CAS
    ``media_type`` (subtitle tracks keep .srt/.vtt/.ass) with a consuming-op role fallback. Any
    genuinely unrenderable kind is reported, in operation order, in ``unrendered_kinds``.
    ``base_revision_id`` must be the current head and the lowered operations' canonical ids must
    exactly equal that revision's stored ids, so a receipt can never claim a revision the
    operations did not build.
    """
    head = get_edit_project(project, edit_project_id)
    if base_revision_id is None or base_revision_id != head.head_revision_id:
        raise contract_error("supplied base revision does not match the current head", INVALID_RECORD)
    # Bind the lowering to the durable revision it claims: the record must exist, belong to this
    # edit project, and the canonical ids of the passed operations must equal its stored ids.
    revision = next((r for r in read_records(project, "edit_revision") if r.record_id == base_revision_id), None)
    if revision is None or revision.edit_project_id != edit_project_id:
        raise contract_error("supplied base revision is not a revision of this edit project", INVALID_RECORD)
    # Normalize once (operations may be a one-shot generator) and reuse the list everywhere below.
    normalized = [_normalize_operation(descriptor, index) for index, descriptor in enumerate(operations)]
    if tuple(_operation_id(op) for op in normalized) != revision.operation_ids:
        raise contract_error("supplied operations do not match the base revision", INVALID_RECORD)

    renderable = [op for op in normalized if op.kind in _RENDERABLE_KINDS]
    # burn_in's second source is the subtitle track: it picks up a subtitle extension when the
    # CAS media_type does not already name one. Declare only sources read by the lowered steps,
    # verified and addressed by opaque job-relative paths with media-type-derived extensions.
    subtitle_digests = {op.sources[1] for op in renderable if op.kind == "burn_in"}
    unique_digests = sorted({digest for op in renderable for digest in op.sources})
    source_ids: dict[str, str] = {}
    source_digests: dict[str, str] = {}
    sources: dict[str, dict[str, str]] = {}
    for index, digest in enumerate(unique_digests):
        resolve_blob(project, digest)
        source_id = f"src{index}"
        source_ids[digest] = source_id
        source_digests[source_id] = digest
        ext = _source_extension(project, digest, subtitle_role=digest in subtitle_digests)
        sources[source_id] = {"path": f"{_SOURCES_DIR}/{source_id}{ext}"}
    steps: list[dict[str, Any]] = []
    outputs: dict[str, dict[str, str]] = {}
    for renderable_index, op in enumerate(renderable):
        output_id = f"out{renderable_index}"
        outputs[output_id] = {"path": f".kinocut/repurpose/out_{renderable_index}.mp4"}
        _lower_operation(op, source_ids, output_id, steps)
    if not steps:
        raise contract_error("slice has no renderable operations to lower into a workflow spec", INVALID_RECORD)
    unrendered = tuple(op.kind for op in normalized if op.kind not in _RENDERABLE_KINDS)
    spec: dict[str, Any] = {
        "schema_version": 1,
        "name": "repurpose_slice",
        "sources": sources,
        "steps": steps,
        "outputs": outputs,
    }
    return WorkflowSpecSynthesis(spec=spec, unrendered_kinds=unrendered, source_digests=source_digests)


def _file_sha256(path: Path) -> str:
    """Stream-hash a file's bytes to its canonical ``sha256:<hex>`` digest."""
    hasher = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(_CHUNK):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _declared_source_path(source_id: str, spec_entry: Any, job_dir: Path, resolved_sources: Path) -> Path:
    """Resolve a spec-declared source path, re-confined under ``sources/`` with a closed name.

    The declared path is workspace-relative (``sources/<id>.<ext>``); binding + confinement are
    re-derived here (never trusting the spec blindly) so materialization links at exactly the
    path synthesis declared and a tampered spec cannot escape the sources directory.
    """
    if not isinstance(spec_entry, Mapping) or not isinstance(spec_entry.get("path"), str):
        raise contract_error(f"source {source_id} has no declared path in the workflow spec", INVALID_RECORD)
    raw_path = spec_entry["path"]
    if not raw_path:
        raise contract_error(f"source {source_id} declares an empty path", INVALID_RECORD)
    declared = job_dir / raw_path  # workspace-relative path bound to the job dir
    # The basename must be exactly <source_id>.<ext>; the path must stay strictly under sources/.
    if declared.stem != source_id or not declared.suffix:
        raise contract_error("declared source path name does not match the closed-form source id", INVALID_RECORD)
    if declared.is_symlink() or (declared.exists() and not declared.is_file()):
        raise contract_error("declared source path already exists as a non-file or symlink", INVALID_RECORD)
    if resolved_sources not in declared.resolve().parents and declared.resolve() != resolved_sources:
        raise contract_error("declared source path escapes the sources directory", INVALID_RECORD)
    return declared


def materialize_workflow_sources(
    project: Project,
    job_id: str,
    synthesis: WorkflowSpecSynthesis,
) -> None:
    """Hard-link each declared source's integrity-checked CAS blob into the frozen job dir.

    :func:`synthesize_workflow_spec` declares opaque job-relative paths
    (``sources/<id>.<ext>`` with the extension derived from each source's CAS ``media_type``)
    to avoid leaking the CAS layout; this seam re-reads those declared paths from the spec,
    re-confines them, and hard-links each integrity-checked CAS blob. Declaration and
    materialization share the one spec source map; CAS and the job dir share one filesystem, so a
    hard link is always achievable and NO copy fallback exists.

    Fail-closed and idempotent: a matching preexisting target is accepted; any wrong
    content/type, symlinked component, non-closed-form id, or escaping path raises
    before linking, so a torn prior run never silently serves wrong bytes.
    """
    if not isinstance(synthesis, WorkflowSpecSynthesis):
        raise contract_error("synthesis must be a WorkflowSpecSynthesis", INVALID_RECORD)
    if not isinstance(synthesis.source_digests, Mapping):
        raise contract_error("synthesis.source_digests must be a mapping", INVALID_RECORD)
    if not isinstance(synthesis.spec, Mapping):
        raise contract_error("synthesis.spec must be a mapping", INVALID_RECORD)
    spec_sources = synthesis.spec.get("sources")
    if not isinstance(spec_sources, Mapping):
        raise contract_error("synthesis.spec.sources must be a mapping", INVALID_RECORD)
    job_dir = job_spec_path(project, job_id).parent
    sources_root = job_dir / _SOURCES_DIR
    if sources_root.is_symlink():
        raise contract_error("sources directory already exists as a symlink", INVALID_RECORD)
    sources_root.mkdir(parents=True, exist_ok=True)
    resolved_sources = sources_root.resolve()
    for source_id, digest in synthesis.source_digests.items():
        if not isinstance(source_id, str) or _SOURCE_ID_RE.fullmatch(source_id) is None:
            raise contract_error("source id must be a synthesis-generated closed form (src<digits>)", INVALID_RECORD)
        _require_digest(digest, "source digest")
        cas_path = resolve_blob(project, digest)  # integrity-checked CAS blob
        declared = _declared_source_path(source_id, spec_sources.get(source_id), job_dir, resolved_sources)
        if declared.exists():
            if _file_sha256(declared) != digest:
                raise contract_error("declared source path already exists with different content", INVALID_RECORD)
            continue  # idempotent: existing target already matches the digest
        try:
            os.link(cas_path, declared)
        except FileExistsError:  # race between the exists() check and the link — re-verify then accept or fail
            if _file_sha256(declared) != digest:
                raise contract_error(
                    "declared source path already exists with different content", INVALID_RECORD
                ) from None
        except OSError as exc:
            raise contract_error("a project-store filesystem operation failed", INVALID_RECORD) from exc
