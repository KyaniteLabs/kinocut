"""Image MCP tool registrations."""

from __future__ import annotations

from typing import Any

from .server_app import _result, _safe_tool, mcp
from .ffmpeg_helpers import _validate_input_path


@mcp.tool()
@_safe_tool
def image_extract_colors(
    image_path: str,
    n_colors: int = 5,
) -> dict[str, Any]:
    """Extract dominant colors from an image or video frame.

    Uses K-means clustering to find the most prominent colors. Returns hex codes,
    RGB values, CSS color names, and percentage coverage.

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        n_colors: Number of dominant colors to extract (1-20, default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import extract_colors

    return _result(extract_colors(image_path, n_colors=n_colors))


@mcp.tool()
@_safe_tool
def image_generate_palette(
    image_path: str,
    harmony: str = "complementary",
    n_colors: int = 5,
) -> dict[str, Any]:
    """Generate a color harmony palette from an image or video frame.

    Extracts the dominant color and generates harmonious colors based on
    color theory (complementary, analogous, triadic, split_complementary).

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        harmony: Harmony type (complementary, analogous, triadic, split_complementary).
        n_colors: Number of dominant colors to base palette on (default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import generate_palette

    return _result(generate_palette(image_path, harmony=harmony, n_colors=n_colors))


@mcp.tool()
@_safe_tool
def image_analyze_product(
    image_path: str,
    use_ai: bool = False,
    n_colors: int = 5,
) -> dict[str, Any]:
    """Analyze a product image or video frame — extract colors and optionally generate AI description.

    Extracts dominant colors from an image. Optionally uses Claude Vision to
    generate a natural language description of the product.

    Args:
        image_path: Absolute path to the image or video file. If video, extracts a representative frame.
        use_ai: If True, use Claude Vision to generate a description (requires ANTHROPIC_API_KEY).
        n_colors: Number of dominant colors to extract (default 5).
    """
    image_path = _validate_input_path(image_path)
    from .image_engine import analyze_product

    return _result(analyze_product(image_path, use_ai=use_ai, n_colors=n_colors))


@mcp.tool()
@_safe_tool
def still_match(
    hero: str,
    inputs: list[str],
    output_dir: str,
) -> dict[str, Any]:
    """Match a package of stills to a hero plate with one shared WB/exposure gain.

    Does not overwrite sources. Writes matched stills + JSON receipt under output_dir.
    Per-frame auto-WB is disabled (shared gains only).

    Args:
        hero: Absolute path to the hero/establish still.
        inputs: Absolute paths to package stills.
        output_dir: Absolute directory for outputs and receipt.
    """
    hero = _validate_input_path(hero)
    safe_inputs = [_validate_input_path(p) for p in inputs]
    from .still_plates import still_match as _still_match

    return _result(_still_match(hero=hero, inputs=safe_inputs, output_dir=output_dir))


@mcp.tool()
@_safe_tool
def still_grade(
    inputs: list[str],
    output_dir: str,
    hero: str | None = None,
    lut_path: str | None = None,
    signal_mode: bool = False,
) -> dict[str, Any]:
    """Grade stills in order correct→match→look; optional 3D LUT applied last.

    Signal mode marks the LUT as signal-alignment (not film cosplay) and records
    near-black/near-white preservation deltas.

    Args:
        inputs: Absolute still paths.
        output_dir: Absolute output directory.
        hero: Optional hero still for match stage.
        lut_path: Optional absolute .cube/.3dl path applied last.
        signal_mode: Treat LUT as signal alignment.
    """
    safe_inputs = [_validate_input_path(p) for p in inputs]
    if hero is not None:
        hero = _validate_input_path(hero)
    from .still_plates import still_grade as _still_grade

    return _result(
        _still_grade(
            inputs=safe_inputs,
            output_dir=output_dir,
            hero=hero,
            lut_path=lut_path,
            signal_mode=signal_mode,
        )
    )


@mcp.tool()
@_safe_tool
def still_gate(
    inputs: list[str],
    output_dir: str,
) -> dict[str, Any]:
    """Fail-closed cohesion gate for a still package + contact sheet.

    Checks luma spread and shadow green/cyan wash. Returns passed=false with
    named metric/frame failures when the package fails.

    Args:
        inputs: Absolute still paths in the package.
        output_dir: Absolute directory for receipt and contact sheet.
    """
    safe_inputs = [_validate_input_path(p) for p in inputs]
    from .still_plates import still_gate as _still_gate

    return _result(_still_gate(inputs=safe_inputs, output_dir=output_dir))


@mcp.tool()
@_safe_tool
def image_edit(
    source: str,
    reference: str,
    intent: str,
    output_dir: str,
    prefer: str = "edit",
    allow_paid_gen: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Free establish-locked still edit with plan/receipt.

    Prefers free edit backends. Paid gen is off unless allow_paid_gen=True.
    Dry-run returns a plan without mutating pixels.

    Args:
        source: Absolute source still path.
        reference: Absolute establish/reference still path.
        intent: Natural-language edit intent.
        output_dir: Absolute output directory.
        prefer: 'edit' (default) or 'gen'.
        allow_paid_gen: Explicit paid generative permission (default False).
        dry_run: Plan only when True.
    """
    source = _validate_input_path(source)
    reference = _validate_input_path(reference)
    from .still_plates import image_edit as _image_edit

    return _result(
        _image_edit(
            source=source,
            reference=reference,
            intent=intent,
            output_dir=output_dir,
            prefer=prefer,
            allow_paid_gen=allow_paid_gen,
            dry_run=dry_run,
        )
    )


@mcp.tool()
@_safe_tool
def still_package(
    establish: str,
    beats: list[str],
    output_dir: str,
    dry_run: bool = False,
    apply_grade: bool = True,
    lut_path: str | None = None,
    signal_mode: bool = False,
) -> dict[str, Any]:
    """Multi-still package workflow: edit beats → match → grade → cohesion gate.

    Args:
        establish: Absolute establish/hero still.
        beats: Absolute beat still paths.
        output_dir: Absolute package output directory.
        dry_run: When True, return planned graph only.
        apply_grade: Run ordered grade after match (default True).
        lut_path: Optional LUT path for grade look stage.
        signal_mode: Signal-alignment LUT mode.
    """
    establish = _validate_input_path(establish)
    safe_beats = [_validate_input_path(p) for p in beats]
    from .still_plates import still_package as _still_package

    return _result(
        _still_package(
            establish=establish,
            beats=safe_beats,
            output_dir=output_dir,
            dry_run=dry_run,
            apply_grade=apply_grade,
            lut_path=lut_path,
            signal_mode=signal_mode,
        )
    )
