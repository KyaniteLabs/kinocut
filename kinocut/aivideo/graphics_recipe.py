"""Deterministic receipt-bound text/logo/caption composition (Wave 5 Task 9).

Composes prescribed text/logo/caption layers over the shipped
:func:`kinocut.engine_composite_layers.composite_layers` primitives. The recipe
is content-addressed by its canonical intent (background asset id + font hash +
normalized parameter hash) and bound to the exact source/font/output bytes via a
tamper-evident receipt. Exact text/logos are deterministic editor layers — every
generative field is rejected at the public boundary so exact pixels can never
route through a generative provider. Fail-closed TOCTOU checks prevent
source/font substitution between authorization and render.

Validation, canvas normalization, the receipt-safe layer form, the canonical
parameter payload, the recipe-intent hash, and the full receipt builder live in
:mod:`kinocut.aivideo.graphics_recipe_checks`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from kinocut.aivideo.protection import (
    MutationIntent,
    MutationOperation,
    assert_no_protected_collision,
)
from kinocut.contracts._common import Sha256, ValueObject
from kinocut.contracts.asset import AssetRecord, GenerationLineage, MediaKind
from kinocut.engine_composite_layers import (
    _build_ffmpeg_args,
    _build_filter_complex,
    _build_layer_plan,
    _file_hash,
    _load_spec,
    _parse_canvas,
    _parse_layers,
    _resolve_output_path,
    _validate_spec_path,
)
from kinocut.engine_runtime_utils import _timed_operation
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
    _validate_input_path,
)
from kinocut.projectstore import Project, append_record, ingest_asset
from kinocut.projectstore import layout, read_records, store

# Shared types, validation, and payload helpers live in the checks module to
# keep this facade under the 800 LOC module ceiling. Symbols re-exported below.
from kinocut.aivideo.graphics_recipe_checks import (
    GraphicsLayer,
    GraphicsLayerKind,
    _PARAMETER_ERROR_CODE,
    _build_layer_spec,
    _build_receipt_payload,
    _canonical,
    _compute_intent,
    _digest,
    _graphics_error,
    _normalized_canvas,
    _sha256,
    _validated_layers,
    _verify_workspace_copies,
)
from kinocut.defaults import DEFAULT_HASH_CHUNK_BYTES

# Stable receipt-protocol identifiers — point-of-use constants, not tunable
# defaults (the generator model and provider id pin the receipt's lineage;
# the receipt name pins the artifact's filename in project storage).
_GENERATOR_MODEL = "kinocut.graphics_recipe.v1"
_PROVIDER_ID = "local_ffmpeg"
_RECEIPT_NAME = "graphics-receipt.json"
_SHA_ADAPTER = TypeAdapter(Sha256)

__all__ = [
    "GraphicsLayer",
    "GraphicsLayerKind",
    "GraphicsResult",
    "compose_graphics_recipe",
]


class GraphicsResult(ValueObject):
    """A bound receipt-bound graphics composition result."""

    recipe_hash: Sha256
    parameter_hash: Sha256
    source_asset_hashes: tuple[Sha256, ...]
    font_hash: Sha256
    output_hash: Sha256
    receipt_hash: Sha256
    asset: AssetRecord
    receipt_artifact_id: Sha256
    receipt_artifact_location: str
    layer_artifact_ids: tuple[Sha256, ...]


def _mutation_intent(recipe_hash: str, authorization_decision_ids: tuple[str, ...] = ()) -> MutationIntent:
    """Build the engine-owned EDIT_GRAPHIC dependency footprint for the recipe."""

    return MutationIntent(
        operation=MutationOperation.EDIT_GRAPHIC,
        graphic=recipe_hash,
        authorization_decision_ids=authorization_decision_ids,
    )


def _validate_sha256(value: str, label: str) -> None:
    try:
        _SHA_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise _graphics_error(f"{label} is invalid", _PARAMETER_ERROR_CODE) from exc


def _resolve_logo_hashes(
    layers: list[GraphicsLayer],
) -> tuple[list[tuple[int, str]], dict[int, str]]:
    """Validate and hash every logo layer src up front."""

    pairs = [
        (index, _validate_input_path(layer.src))  # type: ignore[arg-type]
        for index, layer in enumerate(layers)
        if layer.kind is GraphicsLayerKind.LOGO
    ]
    hashes = {index: _sha256(Path(validated)) for index, validated in pairs}
    return pairs, hashes


def _verified_file_copy(src: str | Path, dst: Path, expected_hash: str) -> Path:
    """Copy ``src`` to ``dst`` while verifying the result matches ``expected_hash``.

    Detects mid-copy source mutation via stat markers (size, mtime, ctime, inode,
    device) and rejects any substitution with a stable ``graphics_source_changed``
    error. The destination is fsynced before the function returns.
    """

    src_path = Path(_validate_input_path(str(src)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    with src_path.open("rb") as source_handle:
        before = os.fstat(source_handle.fileno())
        with dst.open("wb") as writer:
            while chunk := source_handle.read(DEFAULT_HASH_CHUNK_BYTES):
                hasher.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        after = os.fstat(source_handle.fileno())
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, marker) != getattr(after, marker) for marker in markers):
        raise _graphics_error("source changed during verified copy", "graphics_source_changed")
    actual = "sha256:" + hasher.hexdigest()
    if actual != expected_hash:
        raise _graphics_error("verified copy does not match its expected hash", "graphics_source_changed")
    return dst


def _pre_render_text_layer(
    text: str,
    font_path: str,
    size: int,
    color: str,
    canvas: dict[str, Any],
    output: Path,
) -> None:
    """Render ``text`` to a transparent RGBA PNG via FFmpeg drawtext.

    All user-controlled values are escaped via ``_escape_ffmpeg_filter_value``
    before they enter the filter string, mirroring ``engine_text.add_text``.
    """

    safe_text = _escape_ffmpeg_filter_value(text)
    safe_font = _escape_ffmpeg_filter_value(font_path)
    safe_color = _escape_ffmpeg_filter_value(color)
    safe_size = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(size, "text size")))
    vf = (
        f"drawtext=text='{safe_text}':expansion=none:"
        f"fontsize={safe_size}:fontcolor={safe_color}:"
        f"fontfile={safe_font}:x=0:y=0"
    )
    canvas_filter = f"color=c=black@0.0:size={int(canvas['width'])}x{int(canvas['height'])}:duration=0.04,format=rgba"
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            canvas_filter,
            "-frames:v",
            "1",
            "-update",
            "1",
            "-vf",
            vf,
            str(output),
        ]
    )


def _build_composite_spec(
    canvas: dict[str, Any],
    background_src: str,
    layer_specs: list[dict[str, Any]],
    output_path: str,
) -> dict[str, Any]:
    layers = [{"id": "background", "type": "video", "src": background_src, "position": {"x": 0, "y": 0}}]
    layers.extend(layer_specs)
    return {"canvas": canvas, "layers": layers, "output": {"path": output_path, "format": "mp4"}}


def _render_composition(spec_path: Path, output_path: Path) -> dict[str, Any]:
    """Render one composite_layers spec via the shipped private helpers."""

    spec_resolved = _validate_spec_path(str(spec_path))
    spec_data, spec_bytes = _load_spec(spec_resolved)
    canvas = _parse_canvas(spec_data.get("canvas"))
    layers = _parse_layers(spec_data, spec_resolved.parent)
    output = _resolve_output_path(str(output_path), spec_resolved, spec_data)
    filter_complex = _build_filter_complex(canvas, layers)
    args = _build_ffmpeg_args(canvas, layers, filter_complex, output)
    receipt = _build_layer_plan(spec_bytes, canvas, layers, filter_complex, output, spec_resolved.parent)
    with _timed_operation() as _timing:
        _run_ffmpeg(args)
    receipt["output_hash"] = _file_hash(output)
    return receipt


def _active_source(project: Project, asset_id: str) -> tuple[AssetRecord, Path]:
    """Resolve the one active video asset for ``asset_id`` and verify its bytes."""

    records = [r for r in read_records(project, "asset_record") if type(r) is AssetRecord]
    superseded = {r.supersedes for r in records if r.supersedes is not None}
    matches = [r for r in records if r.asset_id == asset_id and r.record_id not in superseded]
    if len(matches) != 1:
        raise _graphics_error("background asset is missing or ambiguous", "graphics_integrity_failed")
    source = matches[0]
    if source.media_kind is not MediaKind.VIDEO:
        raise _graphics_error("background asset must be a video", "graphics_integrity_failed")
    path = store.safe_target(project, source.original_location)
    if not path.is_file():
        raise _graphics_error("background asset file is missing", "graphics_integrity_failed")
    if _sha256(path) != source.asset_id:
        raise _graphics_error("background asset integrity check failed", "graphics_integrity_failed")
    return source, path


def _install_receipt(project: Project, payload: dict[str, Any]) -> tuple[str, str]:
    """Install the canonical receipt artifact (content-addressed, idempotent)."""

    content = _canonical(payload)
    artifact_id = _digest(content)
    rel = layout.artifact_relative_path(artifact_id, _RECEIPT_NAME)
    destination = store.safe_target(project, rel)
    with store._mapped_os_errors():
        destination.parent.mkdir(parents=True, exist_ok=True)
        exists = destination.exists()
    if exists:
        if _sha256(destination) != artifact_id:
            raise _graphics_error("receipt artifact integrity check failed", "graphics_integrity_failed")
        return artifact_id, str(rel)
    with store._mapped_os_errors():
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".graphics.", suffix=".tmp")
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, destination)
            except FileExistsError:
                if _sha256(destination) != artifact_id:
                    raise _graphics_error(
                        "receipt artifact integrity check failed", "graphics_integrity_failed"
                    ) from None
            store._fsync_dir(destination.parent)
        finally:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
    return artifact_id, str(rel)


def _enrich_asset(project: Project, asset: AssetRecord, source: AssetRecord, artifact_id: str) -> AssetRecord:
    """Bind the published asset to its source and receipt artifact (idempotent)."""

    if asset.parent_asset_id == source.asset_id and artifact_id in asset.derived_artifact_ids:
        return asset
    enriched = asset.model_copy(
        update={
            "record_id": None,
            "supersedes": asset.record_id,
            "parent_asset_id": source.asset_id,
            "variant_of": source.asset_id,
            "derived_artifact_ids": (artifact_id,),
        }
    )
    try:
        return cast(AssetRecord, append_record(project, enriched))
    except MCPVideoError:
        records = [r for r in read_records(project, "asset_record") if type(r) is AssetRecord]
        superseded = {r.supersedes for r in records if r.supersedes is not None}
        matches = [r for r in records if r.asset_id == asset.asset_id and r.record_id not in superseded]
        if (
            len(matches) == 1
            and matches[0].parent_asset_id == source.asset_id
            and artifact_id in matches[0].derived_artifact_ids
        ):
            return matches[0]
        raise


def _prior_publication(project: Project, recipe_hash: str) -> GraphicsResult | None:
    """Return an already-published result for this exact recipe, if present."""

    records = [r for r in read_records(project, "asset_record") if type(r) is AssetRecord]
    superseded = {r.supersedes for r in records if r.supersedes is not None}
    matches = [
        r
        for r in records
        if r.record_id not in superseded
        and r.lineage is not None
        and r.lineage.generator_model == _GENERATOR_MODEL
        and r.lineage.generation_settings_hash == recipe_hash
    ]
    if len(matches) != 1 or not matches[0].derived_artifact_ids:
        return None
    asset = matches[0]
    artifact_id = asset.derived_artifact_ids[0]
    rel = layout.artifact_relative_path(artifact_id, _RECEIPT_NAME)
    artifact = store.safe_target(project, rel)
    if not artifact.is_file() or _sha256(artifact) != artifact_id:
        raise _graphics_error("receipt artifact integrity check failed", "graphics_integrity_failed")
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _graphics_error("receipt artifact is invalid", "graphics_integrity_failed") from exc
    return _result_from_payload(asset, artifact_id, str(rel), payload)


def _result_from_payload(
    asset: AssetRecord, artifact_id: str, artifact_location: str, payload: dict[str, Any]
) -> GraphicsResult:
    return GraphicsResult(
        recipe_hash=payload["recipe_hash"],
        parameter_hash=payload["parameter_hash"],
        source_asset_hashes=tuple(payload["source_asset_hashes"]),
        font_hash=payload["font_hash"],
        output_hash=payload["output_hash"],
        receipt_hash=payload["receipt_hash"],
        asset=asset,
        receipt_artifact_id=artifact_id,
        receipt_artifact_location=artifact_location,
        layer_artifact_ids=tuple(payload.get("layer_artifact_ids", ())),
    )


def _render_in_workspace(
    project: Project,
    *,
    source: AssetRecord,
    source_path: Path,
    font_validated: str,
    font_hash: str,
    validated_layers: list[GraphicsLayer],
    canvas: dict[str, Any],
    logo_path_pairs: list[tuple[int, str]],
    logo_hashes: dict[int, str],
) -> tuple[Path, str, list[str]]:
    """Render the composition in a private workspace and return output + hashes."""

    work_root = store.safe_target(project, layout.artifacts_dir())
    with store._mapped_os_errors(), tempfile.TemporaryDirectory(dir=work_root, prefix=".graphics-render.") as work:
        workspace = Path(work)
        font_copy = _verified_file_copy(font_validated, workspace / "font.ttf", font_hash)
        background_copy = _verified_file_copy(source_path, workspace / "background.mp4", source.asset_id)
        logo_copies: dict[int, tuple[Path, str]] = {}
        for logo_index, logo_validated in logo_path_pairs:
            logo_dst = workspace / f"logo-{logo_index}.png"
            copied = _verified_file_copy(logo_validated, logo_dst, logo_hashes[logo_index])
            logo_copies[logo_index] = (copied, logo_hashes[logo_index])

        layer_specs: list[dict[str, Any]] = []
        layer_artifact_ids: list[str] = []
        for index, layer in enumerate(validated_layers):
            if layer.kind in (GraphicsLayerKind.TEXT, GraphicsLayerKind.CAPTION):
                text_png = workspace / f"text-{index}.png"
                _pre_render_text_layer(
                    layer.text,  # type: ignore[arg-type]
                    str(font_copy),
                    layer.size,
                    layer.color,
                    canvas,
                    text_png,
                )
                layer_artifact_ids.append(_sha256(text_png))
                layer_specs.append(_build_layer_spec(index, layer, str(text_png)))
            else:
                logo_copy, _hash = logo_copies[index]
                layer_specs.append(_build_layer_spec(index, layer, str(logo_copy)))

        output_path = workspace / "composition.mp4"
        spec = _build_composite_spec(canvas, str(background_copy), layer_specs, str(output_path))
        spec_path = workspace / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        _render_composition(spec_path, output_path)
        _verify_workspace_copies(background_copy, source.asset_id, font_copy, font_hash, logo_copies, _sha256)
        output_hash = _sha256(output_path)
        published = work_root / f".graphics-published-{output_hash}.mp4"
        with store._mapped_os_errors():
            output_path.rename(published)
        return published, output_hash, layer_artifact_ids


def _install_and_ingest(
    project: Project,
    *,
    output_path: Path,
    source: AssetRecord,
    recipe_hash: str,
    artifact_id: str,
) -> AssetRecord:
    """Install the receipt, ingest the output asset, and enrich its lineage."""

    lineage = GenerationLineage(
        generator_model=_GENERATOR_MODEL,
        provider_id=_PROVIDER_ID,
        generation_settings_hash=recipe_hash,
        source_asset_ids=(source.asset_id,),
    )
    try:
        asset = ingest_asset(
            project,
            output_path,
            lineage=lineage,
            usage_rights_status=source.usage_rights_status,
            usage_rights_evidence_ref=source.usage_rights_evidence_ref,
        )
    finally:
        with contextlib.suppress(OSError):
            output_path.unlink(missing_ok=True)
    asset = _enrich_asset(project, asset, source, artifact_id)
    stored_output = store.safe_target(project, asset.original_location)
    if not stored_output.is_file() or _sha256(stored_output) != asset.asset_id:
        raise _graphics_error("published composition integrity check failed", "graphics_integrity_failed")
    return asset


def compose_graphics_recipe(
    project: Project,
    *,
    background_asset_id: str,
    font_path: str,
    layers: list[dict[str, Any]],
    canvas: dict[str, Any] | None = None,
    authorization_decision_ids: tuple[str, ...] = (),
) -> GraphicsResult:
    """Render a deterministic prescribed text/logo/caption composition.

    Content-addressed by background asset id + font hash + normalized parameter
    hash; bound to exact source/font/output bytes via a tamper-evident receipt;
    gated by the protected-element precheck. Exact text/logos are deterministic
    editor layers; every generative field is rejected. Fails closed on
    substitution, unsafe locations, unknown kinds, and unauthorized recipes.
    """

    _validate_sha256(background_asset_id, "background asset id")
    font_validated = _validate_input_path(font_path)
    font_hash = _sha256(Path(font_validated))
    validated_layers = _validated_layers(layers)
    source, source_path = _active_source(project, background_asset_id)
    canvas_dict = _normalized_canvas(canvas, str(source_path))
    logo_path_pairs, logo_hashes = _resolve_logo_hashes(validated_layers)
    parameter_hash, recipe_hash = _compute_intent(
        source.asset_id, font_hash, validated_layers, canvas_dict, logo_hashes
    )
    assert_no_protected_collision(project, _mutation_intent(recipe_hash, authorization_decision_ids))
    prior = _prior_publication(project, recipe_hash)
    if prior is not None:
        return prior
    output_path, output_hash, layer_artifact_ids = _render_in_workspace(
        project,
        source=source,
        source_path=source_path,
        font_validated=font_validated,
        font_hash=font_hash,
        validated_layers=validated_layers,
        canvas=canvas_dict,
        logo_path_pairs=logo_path_pairs,
        logo_hashes=logo_hashes,
    )
    receipt_payload = _build_receipt_payload(
        background_asset_id=source.asset_id,
        recipe_hash=recipe_hash,
        parameter_hash=parameter_hash,
        logo_hashes=logo_hashes,
        font_hash=font_hash,
        output_hash=output_hash,
        layer_artifact_ids=layer_artifact_ids,
        canvas=canvas_dict,
        validated_layers=validated_layers,
    )
    receipt_hash = _digest(receipt_payload)
    receipt_payload["receipt_hash"] = receipt_hash
    artifact_id, artifact_location = _install_receipt(project, receipt_payload)
    asset = _install_and_ingest(
        project,
        output_path=output_path,
        source=source,
        recipe_hash=recipe_hash,
        artifact_id=artifact_id,
    )
    return GraphicsResult(
        recipe_hash=recipe_hash,
        parameter_hash=parameter_hash,
        source_asset_hashes=tuple(receipt_payload["source_asset_hashes"]),
        font_hash=font_hash,
        output_hash=output_hash,
        receipt_hash=receipt_hash,
        asset=asset,
        receipt_artifact_id=artifact_id,
        receipt_artifact_location=artifact_location,
        layer_artifact_ids=tuple(layer_artifact_ids),
    )
