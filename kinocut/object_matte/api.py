"""Public object-matte entry: stream decode (#412) + equipment gate (#464)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image

from ..defaults import DEFAULT_OBJECT_MATTE_TIMEOUT, DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_input_path
from ..hyperframes_models import HyperframesJsonResult
from ..limits import MAX_OBJECT_MATTE_EQUIPMENT_SAMPLES
from ..validation import REMOVE_BACKGROUND_OBJECT_BACKEND, REMOVE_BACKGROUND_OBJECT_MODEL
from .encode import assert_alpha_output, write_alpha_video, write_png
from .runtime import make_session, require_object_matte_deps
from .weights import ensure_weights

_DOCS = "docs/PRODUCT_MATTE.md"


def _default_output(input_path: str) -> str:
    from .media import is_still

    path = Path(input_path)
    suffix = ".png" if is_still(input_path) else ".webm"
    return str(path.with_name(f"{path.stem}-cutout{suffix}"))


def _receipt(cut: str, hole: str | None, providers: list[str], cache_hit: bool) -> HyperframesJsonResult:
    if not Path(cut).is_file():
        raise MCPVideoError(
            "Object-matte output was not written.",
            error_type="processing_error",
            code="missing_output",
            docs_url=_DOCS,
        )
    payload: dict[str, Any] = {
        "output": cut,
        "model": REMOVE_BACKGROUND_OBJECT_MODEL,
        "backend": REMOVE_BACKGROUND_OBJECT_BACKEND,
        "providers": providers,
        "cache_hit": cache_hit,
        "docs": _DOCS,
    }
    if hole:
        payload["backgroundOutput"] = hole
    return HyperframesJsonResult(command="remove-background", data=payload, stdout=json.dumps(payload, sort_keys=True))


def _sample_mask(inferred: list[Image.Image], mask: Image.Image) -> Image.Image:
    from .temporal import median_window

    inferred.append(mask)
    del inferred[:-3]
    return median_window(inferred)[-1]


def _write_outputs(
    *,
    dest: str,
    hole: str | None,
    first_cut: Image.Image | None,
    first_hole: Image.Image | None,
    cut_dir: Path,
    hole_dir: Path,
    fps: float,
    count: int,
) -> tuple[str, str | None]:
    if Path(dest).suffix.lower() == ".png":
        if first_cut is None or count != 1:
            raise MCPVideoError(
                "PNG object-matte output accepts a still, not a video",
                error_type="validation_error",
                code="invalid_parameter",
                docs_url=_DOCS,
            )
        written = write_png(first_cut, dest)
        hole_written = write_png(first_hole, hole) if hole and first_hole is not None else None
        return written, hole_written
    written = write_alpha_video(cut_dir, dest, fps, "cut_%06d.png")
    hole_written = write_alpha_video(hole_dir, hole, fps, "hole_%06d.png") if hole else None
    return written, hole_written


def run_object_matte(
    *,
    input_path: str,
    output_path: str | None = None,
    background_output_path: str | None = None,
    device: str = "auto",
    quality: str = "balanced",
    mask_interval: int = DEFAULT_REMOVE_BACKGROUND_MASK_INTERVAL,
    equipment_overlay: str | None = None,
    fail_if_equipment_on_subject: bool = False,
) -> HyperframesJsonResult:
    """Cut a product/object. quality is accepted and ignored (CLI always sends it)."""
    del quality
    require_object_matte_deps()
    from .equipment import apply_equipment_gate
    from .infer import infer_mask
    from .media import (
        apply_alpha,
        charge_scratch,
        is_still,
        iter_source_frames,
        refuse_overlong_video,
        refuse_scratch,
    )

    if mask_interval < 1:
        raise MCPVideoError(
            "mask_interval must be >= 1",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url=_DOCS,
        )
    source = _validate_input_path(input_path)
    dest = assert_alpha_output(output_path or _default_output(source))
    hole = assert_alpha_output(background_output_path) if background_output_path else None
    still = is_still(source)
    if still:
        with Image.open(source) as preview:
            width, height = preview.size
        fps, planned_frames = 30.0, 1
    else:
        fps, planned_frames, width, height = refuse_overlong_video(source)
    weights, cache_hit = ensure_weights()
    session, providers = make_session(weights, device)
    deadline = time.monotonic() + DEFAULT_OBJECT_MATTE_TIMEOUT
    with TemporaryDirectory(prefix="kinocut-object-matte-") as tmp:
        work_dir = Path(tmp)
        cut_dir = work_dir / "cut"
        hole_dir = work_dir / "hole"
        cut_dir.mkdir()
        if hole:
            hole_dir.mkdir()
        refuse_scratch(width, height, planned_frames, bool(hole), work_dir)
        cut, hole_out, subject, samples = _stream_job(
            source=source,
            dest=dest,
            hole=hole,
            width=width,
            height=height,
            fps=fps,
            mask_interval=mask_interval,
            session=session,
            deadline=deadline,
            cut_dir=cut_dir,
            hole_dir=hole_dir,
            still=still,
            planned_frames=planned_frames,
            infer_mask=infer_mask,
            apply_alpha=apply_alpha,
            charge_scratch=charge_scratch,
            iter_source_frames=iter_source_frames,
        )
        apply_equipment_gate(
            subject=subject,
            frames=samples or ([subject.convert("RGB")] if still else samples),
            overlay_path=equipment_overlay,
            fail_if_equipment_on_subject=fail_if_equipment_on_subject,
        )
    return _receipt(cut, hole_out, providers, cache_hit)


def _persist_rgba(
    image: Image.Image,
    *,
    dest: str,
    directory: Path,
    prefix: str,
    count: int,
    used: int,
    charge_scratch,
) -> tuple[Image.Image | None, int]:
    """Keep a still in memory or write one sequenced scratch PNG under the budget."""
    if Path(dest).suffix.lower() == ".png":
        return image, used
    path = directory / f"{prefix}_{count:06d}.png"
    image.save(path)
    return None, charge_scratch(used, path.stat().st_size)


def _require_mask(mask: Image.Image | None) -> Image.Image:
    if mask is None:
        raise MCPVideoError(
            "Object-matte produced no subject mask",
            error_type="processing_error",
            code="object_matte_no_frames",
            docs_url=_DOCS,
        )
    return mask


def _deadline_or_raise(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise MCPVideoError(
            f"Object-matte exceeded {DEFAULT_OBJECT_MATTE_TIMEOUT}s",
            error_type="processing_error",
            code="object_matte_timeout",
            docs_url=_DOCS,
        )


def _stream_job(**kwargs):
    """Stream frames to scratch PNGs; return cut path, hole path, subject mask, samples."""
    source, dest, hole = kwargs["source"], kwargs["dest"], kwargs["hole"]
    width, height, fps = kwargs["width"], kwargs["height"], kwargs["fps"]
    mask_interval, session, deadline = kwargs["mask_interval"], kwargs["session"], kwargs["deadline"]
    cut_dir, hole_dir, still = kwargs["cut_dir"], kwargs["hole_dir"], kwargs["still"]
    planned_frames = int(kwargs["planned_frames"])
    infer_mask, apply_alpha = kwargs["infer_mask"], kwargs["apply_alpha"]
    charge_scratch, iter_source_frames = kwargs["charge_scratch"], kwargs["iter_source_frames"]

    inferred: list[Image.Image] = []
    last_mask: Image.Image | None = None
    first_cut = first_hole = subject = None
    samples: list[Image.Image] = []
    count = used = 0
    sample_every = 1 if still else max(1, planned_frames // MAX_OBJECT_MATTE_EQUIPMENT_SAMPLES)
    for index, image in enumerate(iter_source_frames(source, width, height, deadline=deadline)):
        _deadline_or_raise(deadline)
        if last_mask is None or index % mask_interval == 0:
            last_mask = _sample_mask(inferred, infer_mask(session, image))
        subject = _require_mask(last_mask)
        count += 1
        kept, used = _persist_rgba(
            apply_alpha(image, subject, invert=False),
            dest=dest,
            directory=cut_dir,
            prefix="cut",
            count=count,
            used=used,
            charge_scratch=charge_scratch,
        )
        if kept is not None:
            first_cut = kept
        if hole:
            kept_hole, used = _persist_rgba(
                apply_alpha(image, subject, invert=True),
                dest=hole,
                directory=hole_dir,
                prefix="hole",
                count=count,
                used=used,
                charge_scratch=charge_scratch,
            )
            if kept_hole is not None:
                first_hole = kept_hole
        if (still or index % sample_every == 0) and len(samples) < MAX_OBJECT_MATTE_EQUIPMENT_SAMPLES:
            samples.append(image.copy())
    if subject is None or count < 1:
        raise MCPVideoError(
            "Object-matte extract produced no frames",
            error_type="processing_error",
            code="object_matte_no_frames",
            docs_url=_DOCS,
        )
    written, hole_written = _write_outputs(
        dest=dest,
        hole=hole,
        first_cut=first_cut,
        first_hole=first_hole,
        cut_dir=cut_dir,
        hole_dir=hole_dir,
        fps=fps,
        count=count,
    )
    return written, hole_written, subject, samples
