"""CRUSH glitch effects engine — FFmpeg filter implementations.

Eight glitch/visual corruption effects replicating the CRUSH shader bundle.
Each effect builds an FFmpeg filter chain and delegates execution to shared
helpers from ffmpeg_helpers.
"""

from __future__ import annotations

import math

from .engine_runtime_utils import _build_edit_result, _get_video_stream, _timed_operation
from .errors import ProcessingError
from .ffmpeg_helpers import (
    _run_command,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .models import EditResult


# ---------------------------------------------------------------------------
# Shared internal helpers
# ---------------------------------------------------------------------------

_VIDEO_ENCODE_FLAGS = ["-c:a", "copy", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23"]


def _build_cmd(input_path: str, output: str, vf: str) -> list[str]:
    """Build a minimal FFmpeg command with the given video filter chain."""
    return [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        vf,
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
) -> EditResult:
    """Apply RGB channel shift with optional per-frame noise.

    Args:
        input_path: Input video path.
        output: Output video path.
        amount: Shift distance in pixels. Default 10.0.
        angle: Shift direction in degrees. Default 0 (horizontal).
        noise: Per-frame noise amplitude (0-1). Default 0.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
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
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_rgb_shift", timing)


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
) -> EditResult:
    """Apply horizontal jitter to random scanlines.

    Args:
        input_path: Input video path.
        output: Output video path.
        jitter_amount: Max horizontal displacement in pixels. Default 15.
        frequency: Fraction of rows affected (0-1). Default 0.3.
        speed: Animation speed multiplier. Default 5.
        row_height: Height of each jitter band in pixels. Default 4.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    jitter_amount = _sanitize_ffmpeg_number(jitter_amount, "jitter_amount")
    frequency = _sanitize_ffmpeg_number(frequency, "frequency")
    speed = _sanitize_ffmpeg_number(speed, "speed")
    row_height = max(1, int(_sanitize_ffmpeg_number(row_height, "row_height")))

    # Native-filter approach (was per-pixel geq displacement, ~1-8 s/frame at 1080p
    # — it exceeded the 600 s timeout on real clips). `geq` on a full frame evaluates
    # the shift expression for every pixel of every channel; here it only runs on a
    # tiny 1 x (height/row_height) displacement map (a few hundred cells per frame),
    # and the vectorized `displace` filter applies the per-row horizontal shift to the
    # full frame in one fast pass. Same pattern as glitch_macroblocking's scale trick.
    #
    # `displace` reads the per-pixel shift from the luma of an x-map and a y-map, where
    # luma 128 means "no shift" and the +/-127 range maps to +/-127 px. The x-map holds
    # one random value per band-row (constant across the width after a nearest-neighbour
    # upscale), so every row in a band shares one horizontal jitter. The y-map is flat
    # grey 128 (no vertical shift). `N` (frame index) seeds the random so the jitter
    # animates over time; `speed` scales how fast the per-band pattern reshuffles.
    probe = _run_ffprobe_json(input_path)
    stream = _get_video_stream(probe) or {}
    width = int(stream.get("width") or stream.get("coded_width") or 0)
    height = int(stream.get("height") or stream.get("coded_height") or 0)
    if width <= 0 or height <= 0:
        raise ProcessingError(f"ffprobe {input_path}", 1, "could not determine video dimensions for scanline jitter")
    bands = max(1, (height + row_height - 1) // row_height)

    # x-map luma per band-row (X is always 0 on the 1-px-wide map; Y = band index):
    #   gate = random(Y + N*speed) > 1-frequency  -> only `frequency` fraction of rows jitter
    #   mag  = (random(Y + N*speed + 100000)*2 - 1) * jitter_amount  -> signed shift in px
    #   luma = 128 + (gate ? mag : 0)  (geq clamps to 0..255; 128 = no displacement)
    x_expr = (
        f"128+if(gt(random(Y+N*{speed:.1f}),{1.0 - frequency:.4f}),"
        f"(random(Y+N*{speed:.1f}+100000)*2-1)*{jitter_amount:.1f},0)"
    )
    vf = (
        f"split=3[base][xsrc][ysrc];"
        f"[xsrc]scale=1:{bands}:flags=neighbor,"
        f"geq=lum='{x_expr}':cb=128:cr=128,"
        f"scale={width}:{height}:flags=neighbor,format=gray[xmap];"
        f"[ysrc]scale=2:2:flags=neighbor,geq=lum=128:cb=128:cr=128,"
        f"scale={width}:{height}:flags=neighbor,format=gray[ymap];"
        f"[base][xmap][ymap]displace=edge=smear"
    )

    cmd = _build_cmd(input_path, output, vf)
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_scanline_jitter", timing)


# ---------------------------------------------------------------------------
# Effect 3: Screen Tearing (effect id 8)
# ---------------------------------------------------------------------------


def glitch_screen_tearing(
    input_path: str,
    output: str,
    tear_count: int = 5,
    offset_range: float = 80.0,
    speed: float = 3.0,
) -> EditResult:
    """Apply horizontal screen tearing at random Y positions.

    Args:
        input_path: Input video path.
        output: Output video path.
        tear_count: Number of tear bands. Default 5.
        offset_range: Max horizontal offset in pixels. Default 80.
        speed: Animation speed. Default 3.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    tear_count = int(_sanitize_ffmpeg_number(tear_count, "tear_count"))
    offset_range = _sanitize_ffmpeg_number(offset_range, "offset_range")
    speed = _sanitize_ffmpeg_number(speed, "speed")

    # Fast native screen tearing via the vectorized `displace` filter.
    #
    # The previous implementation used a whole-frame per-pixel `geq` displacement
    # (geq=r='p(X+expr,Y)':...), which evaluated the tear expression at every one
    # of ~2M pixels per frame and ran ~1-8 s/frame at 1080p — pathologically slow,
    # exceeding the 600s FFmpeg timeout on real clips.
    #
    # Screen tearing is a per-ROW horizontal shift: the displacement depends only
    # on Y and T, never on X. So we build a cheap x-displacement MAP at low width
    # (16 px) where the row value encodes the horizontal shift (128 = no shift),
    # evaluate the tear expression there (16*H px instead of W*H px), upscale it to
    # the frame size with nearest-neighbor (preserving crisp per-row banding), and
    # let `displace` apply the offsets across the whole frame in one vectorized
    # pass. The y-displacement map is a constant 128 (horizontal-only shift).
    # Converting the main to planar `gbrp` makes displace shift all color channels
    # equally for full-color tearing.
    #
    # Per-tear amplitude is summed into the map; cap it so the summed displacement
    # stays inside displace's +-127 px map dynamic range.
    amp = min(offset_range, 120.0) / max(1, tear_count) * 2.2
    tear_exprs: list[str] = []
    for i in range(tear_count):
        phase = i * 137.5  # golden-angle spacing for variety
        freq = 0.005 + i * 0.003
        # Per-row pseudo-random sign/magnitude via a high-frequency sin of Y
        # (geq's random() needs a runtime seed; a hashed sin is stable + cheap).
        rnd_freq = 12.9898 + i * 9.123
        rnd_off = 78.233 + i * 13.77
        # Each band is gated so only narrow Y ranges (where sin > 0.95) tear.
        s = f"sin(Y*{freq:.4f}+T*{speed:.4f}+{phase:.4f})"
        tear_exprs.append(f"{amp:.4f}*(gt({s},0.95))*{s}*sin(Y*{rnd_freq:.4f}+{rnd_off:.4f})")

    displacement = "+".join(tear_exprs) if tear_exprs else "0"
    # x-map row value: 128 (no shift) plus the summed tear displacement, clamped
    # to the valid 1..255 map range.
    xexpr = f"clip(128+{displacement},1,255)"

    vf = (
        "split=3[main][src1][src2];"
        f"[src1]scale=16:ih,format=gray,geq=lum='{xexpr}'[xsmall];"
        "[xsmall][main]scale2ref=w=iw:h=ih:flags=neighbor[xmap][main2];"
        "[main2]format=gbrp[main3];"
        "[src2]geq=lum=128,format=gray[ymap];"
        "[main3][xmap][ymap]displace=edge=smear"
    )

    cmd = _build_cmd(input_path, output, vf)
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_screen_tearing", timing)


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
) -> EditResult:
    """Simulate VHS tracking error with color bleed and rolling bands.

    Args:
        input_path: Input video path.
        output: Output video path.
        tracking: Tracking error intensity (0-1). Default 0.5.
        noise_amount: VHS noise intensity (0-1). Default 0.03.
        color_bleed: Red channel shift in pixels. Default 3.
        roll_speed: Vertical roll speed. Default 2.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    tracking = _sanitize_ffmpeg_number(tracking, "tracking")
    noise_amount = _sanitize_ffmpeg_number(noise_amount, "noise_amount")
    color_bleed = _sanitize_ffmpeg_number(color_bleed, "color_bleed")
    roll_speed = _sanitize_ffmpeg_number(roll_speed, "roll_speed")

    # Native-filter approach (was per-pixel geq displacement, ~1-8 s/frame at 1080p
    # — it evaluated p(X+roll,Y) for every pixel of every channel and exceeded the
    # 600 s timeout on real clips). The roll offset depends only on Y and time (it is
    # column-independent), so the vertical-roll shift can be baked into a tiny x-map:
    # geq runs only on a 1 x height displacement column (a few hundred cells per frame),
    # and the vectorized `displace` filter applies the per-row horizontal shift to the
    # full frame in one fast pass. Same pattern as glitch_scanline_jitter / macroblocking.
    #
    # `displace` reads the per-pixel shift from the luma of an x-map and a y-map, where
    # luma 128 means "no shift" and the +/-127 range maps to +/-127 px. The x-map holds
    # one rolling value per row (constant across the width after a nearest-neighbour
    # upscale), so every column in a row shares the same horizontal roll; the y-map is
    # flat grey 128 (no vertical shift). The trailing rgbashift (color bleed) and noise
    # (VHS grain) stages are preserved to keep the rolling-tracking look.
    probe = _run_ffprobe_json(input_path)
    stream = _get_video_stream(probe) or {}
    width = int(stream.get("width") or stream.get("coded_width") or 0)
    height = int(stream.get("height") or stream.get("coded_height") or 0)
    if width <= 0 or height <= 0:
        raise ProcessingError(f"ffprobe {input_path}", 1, "could not determine video dimensions for vhs tracking")

    # 1. Rolling horizontal band: sin-based X offset varying with Y and time
    # Uses ternary (if(x,1,0)) to create discrete band steps instead of step()
    roll_offset = tracking * 40
    roll_expr = (
        f"(sin((Y+T*{roll_speed:.1f}*100)*0.02)*{roll_offset:.1f}*"
        f"if(gt(sin((Y+T*{roll_speed:.1f}*100)*0.005),0.3),1,0))"
    )

    # 2. displace driven by a low-res rolling x-map (luma 128 = no shift)
    # 3. rgbashift for color bleed (red channel offset)
    # 4. noise filter for VHS grain
    noise_strength = int(noise_amount * 100)

    vf = (
        f"split=3[base][xsrc][ysrc];"
        f"[xsrc]scale=1:{height}:flags=neighbor,"
        f"geq=lum='128+{roll_expr}':cb=128:cr=128,"
        f"scale={width}:{height}:flags=neighbor,format=gray[xmap];"
        f"[ysrc]scale=2:2:flags=neighbor,geq=lum=128:cb=128:cr=128,"
        f"scale={width}:{height}:flags=neighbor,format=gray[ymap];"
        f"[base][xmap][ymap]displace=edge=smear,"
        f"rgbashift=rh={color_bleed:.1f}:rv={color_bleed * 0.5:.1f}:bh=-{color_bleed * 0.3:.1f},"
        f"noise=alls={noise_strength}:allf=t+u"
    )

    cmd = _build_cmd(input_path, output, vf)
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_vhs_tracking", timing)


# ---------------------------------------------------------------------------
# Effect 5: Macroblocking (effect id 3)
# ---------------------------------------------------------------------------


def glitch_macroblocking(
    input_path: str,
    output: str,
    block_size: int = 16,
    intensity: float = 0.7,
    color_reduction: float = 0.3,
) -> EditResult:
    """Simulate codec macroblocking artifacts by downscale/upscale + posterize.

    Args:
        input_path: Input video path.
        output: Output video path.
        block_size: Block size in pixels. Default 16.
        intensity: Blend intensity with original (0-1). Default 0.7.
        color_reduction: Color level reduction (0-1). Default 0.3.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
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
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_macroblocking", timing)


# ---------------------------------------------------------------------------
# Effect 6: Datamoshing (effect id 4)
# ---------------------------------------------------------------------------


def glitch_datamoshing(
    input_path: str,
    output: str,
    drift: float = 20.0,
    iframe_interval: int = 30,
) -> EditResult:
    """Simulate datamoshing / P-frame corruption artifacts.

    Uses frame blending with cyclic displacement resets to mimic
    the look of I-frame corruption spreading through P-frames.

    Args:
        input_path: Input video path.
        output: Output video path.
        drift: Max displacement drift in pixels. Default 20.
        iframe_interval: Frame interval for displacement resets. Default 30.

    Returns:
        EditResult with output path, duration, resolution, size, and elapsed_ms.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    drift = _sanitize_ffmpeg_number(drift, "drift")
    iframe_interval = int(_sanitize_ffmpeg_number(max(1, iframe_interval), "iframe_interval"))

    # Build a displacement that grows cyclically (mimicking P-frame drift)
    # then resets every iframe_interval frames, scaled by drift.
    #
    # The previous implementation used a per-pixel `geq=r/g/b=p(X+expr,Y+expr)`
    # 2D displacement. Because the offset was spatially uniform per frame (it
    # depended only on N/T, not on X/Y), geq re-sampled every pixel of every
    # frame for what is mathematically a whole-frame translate — pathologically
    # slow (~1-8 s/frame at 1080p, exceeding the 600 s FFmpeg timeout on real
    # clips). We reproduce the same uniform cyclic drift with a vectorized
    # whole-frame translate: pad the frame, then crop back with a per-frame x/y
    # offset. `tblend` is kept for the frame-merge / P-frame artifact.
    cycle_expr = f"(mod(n,{iframe_interval})/{iframe_interval}*{drift:.1f})"

    # Pad enough to hold the maximum displacement (|sin|,|cos| <= 1 -> max = drift).
    pad = math.ceil(abs(drift)) + 2

    # Crop offsets are centered at `pad` so a zero-drift cycle reset = no shift.
    x_expr = f"{pad}+{cycle_expr}*sin(t*2)"
    y_expr = f"{pad}+{cycle_expr}*cos(t*3)"
    vf = (
        f"tblend=all_mode=grainextract,"
        f"pad=iw+2*{pad}:ih+2*{pad}:{pad}:{pad}:color=black,"
        f"crop=iw-2*{pad}:ih-2*{pad}:x='{x_expr}':y='{y_expr}'"
    )

    cmd = _build_cmd(input_path, output, vf)
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_datamoshing", timing)


# ---------------------------------------------------------------------------
# Effect 7: CMYK Split (effect id 13)
# ---------------------------------------------------------------------------


def glitch_cmyk_split(
    input_path: str,
    output: str,
    amount: float = 8.0,
    angle: float = 0.0,
    noise: float = 0.0,
) -> EditResult:
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
        EditResult with output path, duration, resolution, size, and elapsed_ms.
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
        rgbashift = f"rgbashift=rh={rh:.2f}:rv={rv:.2f}:gh={gh:.2f}:gv={gv:.2f}:bh={bh:.2f}:bv={bv:.2f}"

    # Boost color saturation to enhance the CMYK print look
    vf = f"{rgbashift},colorbalance=rs=0.05:bs=-0.03:gh=0.03"

    cmd = _build_cmd(input_path, output, vf)
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_cmyk_split", timing)


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
) -> EditResult:
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
        EditResult with output path, duration, resolution, size, and elapsed_ms.
    """
    input_path = _validate_input_path(input_path)
    _validate_output_path(output)
    amount = _sanitize_ffmpeg_number(amount, "amount")
    scale = _sanitize_ffmpeg_number(scale, "scale")
    speed = _sanitize_ffmpeg_number(speed, "speed")
    octaves = int(_sanitize_ffmpeg_number(octaves, "octaves"))
    octaves = max(1, min(5, octaves))

    # Fast native-filter turbulent warp.
    #
    # The previous implementation ran a per-pixel `geq=r/g/b='p(X+dx,Y+dy)'` whose
    # lookup expression evaluated a multi-octave trig sum for every channel of
    # every pixel of every frame. At 1080p that is ~1-8 s/frame, so a real clip
    # blows past the 600s FFmpeg timeout (the same bug class fixed for
    # transition_pixelate). Instead we build the displacement field ONCE at a tiny
    # 96x54 resolution with `geq` (cheap: ~5k pixels), upscale it to the source
    # resolution with `scale2ref` (resolution-agnostic, no need to know W/H here),
    # and apply it with the vectorized `displace` filter. `displace` reads each
    # map as an offset (128 = no shift), giving the same turbulent warp orders of
    # magnitude faster (~10s for a 1080p/10s/30fps clip vs. minutes).
    #
    # Map coords run 0..95 / 0..53, so spatial frequencies are multiplied by an
    # upscale reference factor to keep the turbulence scale comparable on the full
    # frame. The octave amplitudes are normalized so the summed displacement stays
    # within +/- `amount` pixels (displace clamps maps to 0..255 i.e. +/-127px).
    map_w = 96
    map_h = 54
    freq_ref = 20.0  # spatial-frequency upscale so low-res map matches full frame

    dx_terms: list[str] = []
    dy_terms: list[str] = []
    amp_sum = 0.0
    for i in range(octaves):
        freq = scale * (2**i) * freq_ref
        amp = 1.0 / (2**i)
        amp_sum += amp
        t_offset = i * 1.7  # phase offset per octave for variety
        dx_terms.append(f"sin(X*{freq:.4f}+Y*{freq * 0.7:.4f}+T*{speed:.1f}+{t_offset:.1f})*{amp:.3f}")
        dy_terms.append(f"cos(X*{freq * 0.8:.4f}+Y*{freq:.4f}+T*{speed:.1f}+{t_offset + 0.5:.1f})*{amp:.3f}")

    dx_expr = "+".join(dx_terms)
    dy_expr = "+".join(dy_terms)
    # Clamp displacement magnitude to the +/-127 px range the maps can encode.
    px = min(amount, 120.0)

    dx_map = f"128+{px:.1f}*({dx_expr})/{amp_sum:.3f}"
    dy_map = f"128+{px:.1f}*({dy_expr})/{amp_sum:.3f}"

    filter_complex = (
        f"[0:v]split=3[base][mx][my];"
        f"[mx]scale={map_w}:{map_h},geq=lum='{dx_map}':cb=128:cr=128,format=gray[mxs];"
        f"[my]scale={map_w}:{map_h},geq=lum='{dy_map}':cb=128:cr=128,format=gray[mys];"
        f"[mxs][base]scale2ref=flags=bilinear[xmap][base1];"
        f"[mys][base1]scale2ref=flags=bilinear[ymap][base2];"
        f"[base2][xmap][ymap]displace=edge=mirror[out]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        *_VIDEO_ENCODE_FLAGS,
        output,
    ]
    with _timed_operation() as timing:
        _run_command(cmd)
    return _build_edit_result(output, "glitch_turbulent_displacement", timing)
