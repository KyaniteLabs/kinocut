"""CRUSH glitch effects engine — FFmpeg filter implementations.

Eight glitch/visual corruption effects replicating the CRUSH shader bundle.
Each effect builds an FFmpeg filter chain and delegates execution to shared
helpers from ffmpeg_helpers.
"""

from __future__ import annotations

import math

from .ffmpeg_helpers import (
    _run_command,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)


# ---------------------------------------------------------------------------
# Shared internal helpers
# ---------------------------------------------------------------------------

_VIDEO_ENCODE_FLAGS = ["-c:a", "copy", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23"]


def _build_cmd(input_path: str, output: str, vf: str) -> list[str]:
    """Build a minimal FFmpeg command with the given video filter chain."""
    return [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        *_VIDEO_ENCODE_FLAGS,
        output,
    ]


# ---------------------------------------------------------------------------
# Effect 1: RGB Shift (effect id 1)
# ---------------------------------------------------------------------------

def glitch_rgb_shift(
    input_path: str,
    output: str,
    amount: float = 10.0,
    angle: float = 0.0,
    noise: float = 0.0,
) -> str:
    """Apply RGB channel shift with optional per-frame noise.

    Args:
        input_path: Input video path.
        output: Output video path.
        amount: Shift distance in pixels. Default 10.0.
        angle: Shift direction in degrees. Default 0 (horizontal).
        noise: Per-frame noise amplitude (0-1). Default 0.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    amount = _sanitize_ffmpeg_number(amount, "amount")
    angle = _sanitize_ffmpeg_number(angle, "angle")
    noise = _sanitize_ffmpeg_number(noise, "noise")

    angle_rad = angle * math.pi / 180.0
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    # Base shift values
    rh = amount * cos_a
    rv = amount * sin_a
    bh = -amount * cos_a
    bv = -amount * sin_a

    if noise > 0:
        # Add time-varying noise to shift amounts via random() expression
        noise_px = noise * amount
        vf = (
            f"rgbashift="
            f"rh='({rh:.2f}+({noise_px:.2f}*(random(0)*2-1)))':"
            f"rv='({rv:.2f}+({noise_px:.2f}*(random(1)*2-1)))':"
            f"bh='({bh:.2f}+({noise_px:.2f}*(random(2)*2-1)))':"
            f"bv='({bv:.2f}+({noise_px:.2f}*(random(3)*2-1)))'"
        )
    else:
        vf = f"rgbashift=rh={rh:.2f}:rv={rv:.2f}:bh={bh:.2f}:bv={bv:.2f}"

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 2: Scanline Jitter (effect id 6)
# ---------------------------------------------------------------------------

def glitch_scanline_jitter(
    input_path: str,
    output: str,
    jitter_amount: float = 15.0,
    frequency: float = 0.3,
    speed: float = 5.0,
    row_height: int = 4,
) -> str:
    """Apply horizontal jitter to random scanlines.

    Args:
        input_path: Input video path.
        output: Output video path.
        jitter_amount: Max horizontal displacement in pixels. Default 15.
        frequency: Fraction of rows affected (0-1). Default 0.3.
        speed: Animation speed multiplier. Default 5.
        row_height: Height of each jitter band in pixels. Default 4.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    jitter_amount = _sanitize_ffmpeg_number(jitter_amount, "jitter_amount")
    frequency = _sanitize_ffmpeg_number(frequency, "frequency")
    speed = _sanitize_ffmpeg_number(speed, "speed")
    row_height = int(_sanitize_ffmpeg_number(row_height, "row_height"))

    # geq-based approach: displace X based on row index and time-modulated random
    # The expression evaluates per-pixel and shifts rows that match the jitter trigger
    vf = (
        f"geq="
        f"r='p("
        f"X+if(lt(random(floor(Y/{row_height})*T*{speed:.1f})*1.0,{frequency:.2f}),"
        f"(random(floor(Y/{row_height})*T*{speed:.1f}+100)*2-1)*{jitter_amount:.1f},0)"
        f",Y)':"
        f"g='p("
        f"X+if(lt(random(floor(Y/{row_height})*T*{speed:.1f})*1.0,{frequency:.2f}),"
        f"(random(floor(Y/{row_height})*T*{speed:.1f}+100)*2-1)*{jitter_amount:.1f},0)"
        f",Y)':"
        f"b='p("
        f"X+if(lt(random(floor(Y/{row_height})*T*{speed:.1f})*1.0,{frequency:.2f}),"
        f"(random(floor(Y/{row_height})*T*{speed:.1f}+100)*2-1)*{jitter_amount:.1f},0)"
        f",Y)'"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 3: Screen Tearing (effect id 8)
# ---------------------------------------------------------------------------

def glitch_screen_tearing(
    input_path: str,
    output: str,
    tear_count: int = 5,
    offset_range: float = 80.0,
    speed: float = 3.0,
) -> str:
    """Apply horizontal screen tearing at random Y positions.

    Args:
        input_path: Input video path.
        output: Output video path.
        tear_count: Number of tear bands. Default 5.
        offset_range: Max horizontal offset in pixels. Default 80.
        speed: Animation speed. Default 3.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    tear_count = int(_sanitize_ffmpeg_number(tear_count, "tear_count"))
    offset_range = _sanitize_ffmpeg_number(offset_range, "offset_range")
    speed = _sanitize_ffmpeg_number(speed, "speed")

    # Build a geq expression that creates tears at Y positions derived from
    # sin functions at different frequencies. Each tear band displaces X
    # by a time-varying offset, creating the classic screen-tear look.
    tear_exprs: list[str] = []
    for i in range(tear_count):
        phase = i * 137.5  # golden-angle spacing for variety
        freq = 0.005 + i * 0.003
        seed = i * 7 + 42
        # Each tear contributes a displacement within a narrow Y band
        # random(N) in geq takes a seed integer; use Y+seed for spatial variation
        tear_exprs.append(
            f"(sin(Y*{freq:.4f}+T*{speed:.1f}+{phase:.1f})*"
            f"if(gt(sin(Y*{freq:.4f}+T*{speed:.1f}+{phase:.1f}),0.95),1,0)*"
            f"{offset_range:.1f}*(random(floor(Y)+{seed})*2-1))"
        )

    displacement = "+".join(tear_exprs) if tear_exprs else "0"

    vf = (
        f"geq="
        f"r='p(X+({displacement}),Y)':"
        f"g='p(X+({displacement}),Y)':"
        f"b='p(X+({displacement}),Y)'"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 4: VHS Tracking (effect id 5)
# ---------------------------------------------------------------------------

def glitch_vhs_tracking(
    input_path: str,
    output: str,
    tracking: float = 0.5,
    noise_amount: float = 0.03,
    color_bleed: float = 3.0,
    roll_speed: float = 2.0,
) -> str:
    """Simulate VHS tracking error with color bleed and rolling bands.

    Args:
        input_path: Input video path.
        output: Output video path.
        tracking: Tracking error intensity (0-1). Default 0.5.
        noise_amount: VHS noise intensity (0-1). Default 0.03.
        color_bleed: Red channel shift in pixels. Default 3.
        roll_speed: Vertical roll speed. Default 2.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    tracking = _sanitize_ffmpeg_number(tracking, "tracking")
    noise_amount = _sanitize_ffmpeg_number(noise_amount, "noise_amount")
    color_bleed = _sanitize_ffmpeg_number(color_bleed, "color_bleed")
    roll_speed = _sanitize_ffmpeg_number(roll_speed, "roll_speed")

    # 1. Rolling horizontal band: sin-based X offset varying with Y and time
    # Uses ternary (if(x,1,0)) to create discrete band steps instead of step()
    roll_offset = tracking * 40
    roll_expr = (
        f"(sin((Y+T*{roll_speed:.1f}*100)*0.02)*{roll_offset:.1f}*"
        f"if(gt(sin((Y+T*{roll_speed:.1f}*100)*0.005),0.3),1,0))"
    )

    # 2. geq for the rolling displacement (applied to all channels)
    # 3. rgbashift for color bleed (red channel offset)
    # 4. noise filter for VHS grain
    noise_strength = int(noise_amount * 100)

    vf = (
        f"geq="
        f"r='p(X+{roll_expr},Y)':"
        f"g='p(X+{roll_expr},Y)':"
        f"b='p(X+{roll_expr},Y)',"
        f"rgbashift=rh={color_bleed:.1f}:rv={color_bleed * 0.5:.1f}:bh=-{color_bleed * 0.3:.1f},"
        f"noise=alls={noise_strength}:allf=t+u"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 5: Macroblocking (effect id 3)
# ---------------------------------------------------------------------------

def glitch_macroblocking(
    input_path: str,
    output: str,
    block_size: int = 16,
    intensity: float = 0.7,
    color_reduction: float = 0.3,
) -> str:
    """Simulate codec macroblocking artifacts by downscale/upscale + posterize.

    Args:
        input_path: Input video path.
        output: Output video path.
        block_size: Block size in pixels. Default 16.
        intensity: Blend intensity with original (0-1). Default 0.7.
        color_reduction: Color level reduction (0-1). Default 0.3.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    block_size = int(_sanitize_ffmpeg_number(max(2, block_size), "block_size"))
    intensity = _sanitize_ffmpeg_number(intensity, "intensity")
    color_reduction = _sanitize_ffmpeg_number(color_reduction, "color_reduction")

    # Posterization: reduce levels based on color_reduction
    # colorlevels input minimum adjustment pushes values toward quantized steps
    levels = color_reduction * 0.3  # subtle posterization

    # Scale down then up with neighbor interpolation for blocky look,
    # then posterize, then blend with original.
    # We use iw*block_size to restore original dimensions after downscale,
    # since "iw" in the second scale refers to the already-downscaled width.
    vf = (
        f"split[orig][blocked];"
        f"[blocked]"
        f"scale='iw/{block_size}':'ih/{block_size}':flags=neighbor,"
        f"scale='iw*{block_size}':'ih*{block_size}':flags=neighbor,"
        f"colorlevels=rimin={levels:.3f}:gimin={levels:.3f}:bimin={levels:.3f}"
        f"[blk];"
        f"[orig][blk]blend=all_expr='A*(1-{intensity:.2f})+B*{intensity:.2f}'"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 6: Datamoshing (effect id 4)
# ---------------------------------------------------------------------------

def glitch_datamoshing(
    input_path: str,
    output: str,
    drift: float = 20.0,
    iframe_interval: int = 30,
) -> str:
    """Simulate datamoshing / P-frame corruption artifacts.

    Uses frame blending with cyclic displacement resets to mimic
    the look of I-frame corruption spreading through P-frames.

    Args:
        input_path: Input video path.
        output: Output video path.
        drift: Max displacement drift in pixels. Default 20.
        iframe_interval: Frame interval for displacement resets. Default 30.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    drift = _sanitize_ffmpeg_number(drift, "drift")
    iframe_interval = int(_sanitize_ffmpeg_number(max(1, iframe_interval), "iframe_interval"))

    # Build a displacement that grows cyclically (mimicking P-frame drift)
    # then resets every iframe_interval frames.
    # Use mod(N,iframe_interval) to get cycle position, scale by drift.
    # Combine with tblend for frame-merge artifacts.
    cycle_expr = f"(mod(N,{iframe_interval})/{iframe_interval}*{drift:.1f})"

    # geq displaces X by the cyclic amount, varying direction with sin
    vf = (
        f"tblend=all_mode=grainextract,"
        f"geq="
        f"r='p(X+{cycle_expr}*sin(T*2),Y+{cycle_expr}*cos(T*3))':"
        f"g='p(X+{cycle_expr}*sin(T*2+1),Y+{cycle_expr}*cos(T*3+1))':"
        f"b='p(X+{cycle_expr}*sin(T*2+2),Y+{cycle_expr}*cos(T*3+2))'"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 7: CMYK Split (effect id 13)
# ---------------------------------------------------------------------------

def glitch_cmyk_split(
    input_path: str,
    output: str,
    amount: float = 8.0,
    angle: float = 0.0,
    noise: float = 0.0,
) -> str:
    """Apply CMYK-style four-channel split at 90-degree offsets.

    Simulates a four-plate offset print registration error by shifting
    RGB channels at 90-degree intervals and applying colorchannelmixer
    adjustments.

    Args:
        input_path: Input video path.
        output: Output video path.
        amount: Shift distance in pixels. Default 8.
        angle: Base angle in degrees. Default 0.
        noise: Per-frame noise amplitude (0-1). Default 0.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    amount = _sanitize_ffmpeg_number(amount, "amount")
    angle = _sanitize_ffmpeg_number(angle, "angle")
    noise = _sanitize_ffmpeg_number(noise, "noise")

    base_rad = angle * math.pi / 180.0

    # Four directions at 90-degree intervals: 0, 90, 180, 270
    # Red shifts at 0, Green at 90, Blue at 180
    r_cos = math.cos(base_rad)
    r_sin = math.sin(base_rad)
    g_cos = math.cos(base_rad + math.pi / 2)
    g_sin = math.sin(base_rad + math.pi / 2)
    b_cos = math.cos(base_rad + math.pi)
    b_sin = math.sin(base_rad + math.pi)

    rh = amount * r_cos
    rv = amount * r_sin
    gh = amount * g_cos
    gv = amount * g_sin
    bh = amount * b_cos
    bv = amount * b_sin

    noise_px = noise * amount

    if noise > 0:
        rgbashift = (
            f"rgbashift="
            f"rh='({rh:.2f}+{noise_px:.2f}*(random(0)*2-1))':"
            f"rv='({rv:.2f}+{noise_px:.2f}*(random(1)*2-1))':"
            f"gh='({gh:.2f}+{noise_px:.2f}*(random(2)*2-1))':"
            f"gv='({gv:.2f}+{noise_px:.2f}*(random(3)*2-1))':"
            f"bh='({bh:.2f}+{noise_px:.2f}*(random(4)*2-1))':"
            f"bv='({bv:.2f}+{noise_px:.2f}*(random(5)*2-1))'"
        )
    else:
        rgbashift = (
            f"rgbashift="
            f"rh={rh:.2f}:rv={rv:.2f}:"
            f"gh={gh:.2f}:gv={gv:.2f}:"
            f"bh={bh:.2f}:bv={bv:.2f}"
        )

    # Boost color saturation to enhance the CMYK print look
    vf = (
        f"{rgbashift},"
        f"colorbalance=rs=0.05:bs=-0.03:gh=0.03"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output


# ---------------------------------------------------------------------------
# Effect 8: Turbulent Displacement (effect id 9)
# ---------------------------------------------------------------------------

def glitch_turbulent_displacement(
    input_path: str,
    output: str,
    amount: float = 20.0,
    scale: float = 0.01,
    speed: float = 1.0,
    octaves: int = 3,
) -> str:
    """Apply turbulent displacement using multi-octave sin/cos approximation.

    Uses layered sin/cos expressions at different frequencies to approximate
    fractional Brownian motion (FBM) noise, then displaces pixels accordingly.

    Args:
        input_path: Input video path.
        output: Output video path.
        amount: Displacement magnitude in pixels. Default 20.
        scale: Base noise frequency. Default 0.01.
        speed: Animation speed. Default 1.
        octaves: Number of noise octaves (1-5). Default 3.

    Returns:
        Path to output video.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    amount = _sanitize_ffmpeg_number(amount, "amount")
    scale = _sanitize_ffmpeg_number(scale, "scale")
    speed = _sanitize_ffmpeg_number(speed, "speed")
    octaves = int(_sanitize_ffmpeg_number(octaves, "octaves"))
    octaves = max(1, min(5, octaves))

    # Build multi-octave displacement expressions
    # Each octave doubles the frequency and halves the amplitude
    dx_terms: list[str] = []
    dy_terms: list[str] = []
    for i in range(octaves):
        freq = scale * (2 ** i)
        amp = 1.0 / (2 ** i)
        t_offset = i * 1.7  # phase offset per octave for variety
        dx_terms.append(f"sin(X*{freq:.4f}+Y*{freq * 0.7:.4f}+T*{speed:.1f}+{t_offset:.1f})*{amp:.3f}")
        dy_terms.append(f"cos(X*{freq * 0.8:.4f}+Y*{freq:.4f}+T*{speed:.1f}+{t_offset + 0.5:.1f})*{amp:.3f}")

    dx_expr = "+".join(dx_terms)
    dy_expr = "+".join(dy_terms)

    vf = (
        f"geq="
        f"r='p(X+({dx_expr})*{amount:.1f},Y+({dy_expr})*{amount:.1f})':"
        f"g='p(X+({dx_expr})*{amount:.1f},Y+({dy_expr})*{amount:.1f})':"
        f"b='p(X+({dx_expr})*{amount:.1f},Y+({dy_expr})*{amount:.1f})'"
    )

    cmd = _build_cmd(input_path, output, vf)
    _run_command(cmd)
    return output
