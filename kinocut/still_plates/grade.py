"""still-grade: correct → match → look pipeline with optional LUT last."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..defaults import STILL_MATCH_MAX_GAIN, STILL_MATCH_MIN_GAIN
from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _escape_ffmpeg_filter_value, _run_ffmpeg
from .io import (
    ensure_output_dir,
    file_sha256,
    load_rgb_array,
    save_rgb_array,
    validate_still_path,
    write_receipt,
)
from .stats import apply_rgb_gains, mean_rgb, shared_gains_to_hero


def _package_mean_rgb(arrs: list) -> tuple[float, float, float]:
    return tuple(float(sum(mean_rgb(a)[i] for a in arrs) / len(arrs)) for i in range(3))


def _pipeline_arrays(arrs: list, hero: str | Path | None):
    package_rgb = _package_mean_rgb(arrs)
    gray = sum(package_rgb) / 3.0
    neutralize_gains = shared_gains_to_hero(
        (gray, gray, gray),
        package_rgb,  # type: ignore[arg-type]
        max_gain=STILL_MATCH_MAX_GAIN,
        min_gain=STILL_MATCH_MIN_GAIN,
    )
    neutralized = [apply_rgb_gains(a, neutralize_gains) for a in arrs]
    match_gains = (1.0, 1.0, 1.0)
    matched = neutralized
    hero_path: Path | None = None
    if hero is not None:
        hero_path = validate_still_path(hero)
        hero_rgb = mean_rgb(load_rgb_array(hero_path))
        match_gains = shared_gains_to_hero(
            hero_rgb,
            _package_mean_rgb(neutralized),  # type: ignore[arg-type]
            max_gain=STILL_MATCH_MAX_GAIN,
            min_gain=STILL_MATCH_MIN_GAIN,
        )
        matched = [apply_rgb_gains(a, match_gains) for a in neutralized]
    return matched, neutralize_gains, match_gains, hero_path


def _export_graded(
    input_paths: list[Path],
    matched: list,
    out_dir: Path,
    lut_path: str | Path | None,
    signal_mode: bool,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for src, arr in zip(input_paths, matched, strict=True):
        intermediate = out_dir / f"{src.stem}_graded_pre_lut.png"
        save_rgb_array(arr, intermediate)
        final_path = out_dir / f"{src.stem}_graded.png"
        if lut_path is not None:
            lut = Path(lut_path).expanduser()
            if not lut.is_file():
                raise MCPVideoError(
                    f"LUT file not found: {lut}",
                    error_type="input_error",
                    code="lut_not_found",
                )
            _apply_lut3d(intermediate, final_path, lut)
            intermediate.unlink(missing_ok=True)
        else:
            shutil.move(str(intermediate), str(final_path))
        preservation = None
        if signal_mode:
            preservation = _near_extrema_preservation(load_rgb_array(src), load_rgb_array(final_path))
        outputs.append(
            {
                "source": str(src),
                "output": str(final_path),
                "source_sha256": file_sha256(src),
                "output_sha256": file_sha256(final_path),
                "near_extrema_preservation": preservation,
            }
        )
    return outputs


def still_grade(
    *,
    inputs: list[str | Path],
    output_dir: str | Path,
    hero: str | Path | None = None,
    lut_path: str | Path | None = None,
    signal_mode: bool = False,
    receipt_name: str = "still_grade_receipt.json",
) -> dict[str, Any]:
    """Grade stills in strict order: neutralize → match → look/LUT last."""
    if not inputs:
        raise MCPVideoError(
            "still-grade requires at least one input still",
            error_type="validation_error",
            code="empty_inputs",
        )
    input_paths = [validate_still_path(p) for p in inputs]
    out_dir = ensure_output_dir(output_dir)
    stages = ["neutralize", "match"] + (["look_lut"] if lut_path is not None else [])
    arrs = [load_rgb_array(p) for p in input_paths]
    matched, neutralize_gains, match_gains, hero_path = _pipeline_arrays(arrs, hero)
    outputs = _export_graded(input_paths, matched, out_dir, lut_path, signal_mode)
    receipt = {
        "tool": "still_grade",
        "stages": stages,
        "pipeline_order": "correct→match→look",
        "signal_mode": signal_mode,
        "signal_lut_note": (
            "Signal-alignment LUTs only; not film-emulation packs" if signal_mode or lut_path else None
        ),
        "neutralize_gains": list(neutralize_gains),
        "match_gains": list(match_gains),
        "hero": str(hero_path) if hero_path else None,
        "lut_path": str(lut_path) if lut_path else None,
        "outputs": outputs,
        "status": "ok",
    }
    receipt_path = write_receipt(out_dir / receipt_name, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["output_dir"] = str(out_dir)
    return receipt


def _apply_lut3d(src: Path, dest: Path, lut: Path) -> None:
    """Apply a .cube/.3dl LUT via FFmpeg lut3d (look stage last)."""
    safe_lut = _escape_ffmpeg_filter_value(str(lut.resolve()))
    try:
        _run_ffmpeg(["-i", str(src), "-vf", f"lut3d=file='{safe_lut}'", "-frames:v", "1", str(dest)])
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("ffmpeg-lut3d", 1, str(exc)[:500]) from exc
    if not dest.is_file():
        raise ProcessingError("ffmpeg-lut3d", 1, f"LUT output missing: {dest}")


def _near_extrema_preservation(before, after) -> dict[str, float | bool | None]:
    """Measure mean-luma shift in near-black / near-white bands (signal mode).

    Empty bands are not treated as 0.0 (that made missing extrema look like
    perfect black and inflated deltas). When either side lacks the band,
    the delta is null and ``*_band_empty`` is true.
    """
    from ..defaults import STILL_NEAR_BLACK_MAX, STILL_NEAR_WHITE_MIN

    def band_mean_luma(arr, lo: float, hi: float) -> float | None:
        luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
        mask = (luma >= lo) & (luma <= hi)
        if not mask.any():
            return None
        return float(luma[mask].mean())

    def band_delta(lo: float, hi: float) -> tuple[float | None, bool]:
        b = band_mean_luma(before, lo, hi)
        a = band_mean_luma(after, lo, hi)
        if b is None or a is None:
            return None, True
        return abs(a - b), False

    nb_delta, nb_empty = band_delta(0.0, STILL_NEAR_BLACK_MAX)
    nw_delta, nw_empty = band_delta(STILL_NEAR_WHITE_MIN, 1.0)
    return {
        "near_black_delta": nb_delta,
        "near_white_delta": nw_delta,
        "near_black_band_empty": nb_empty,
        "near_white_band_empty": nw_empty,
        "near_black_max": STILL_NEAR_BLACK_MAX,
        "near_white_min": STILL_NEAR_WHITE_MIN,
    }
