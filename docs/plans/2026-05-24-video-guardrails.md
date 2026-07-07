# Video Guardrails Implementation Plan

**Goal:** Add validation guardrails to the most impactful video/audio components to prevent silent bad output.

**Architecture:** Extend the existing guardrail pattern from `design_guardrails.py` — pre-operation validation functions that return warnings/errors, called by engine functions before FFmpeg execution. Reuse existing helpers (`_sanitize_ffmpeg_number`, `_validate_color`, `_escape_ffmpeg_filter_value`). Follow AGENTS.md rules (no bare exceptions, custom error types, timeout on subprocess, defaults from `defaults.py`).

**Tech Stack:** Python 3.11+, FFmpeg, pytest, existing `mcp_video` engine modules

---

## Prerequisites

Before any task, verify the environment:

```bash
cd <repo>
python3 -c "import mcp_video; print('OK')"
python3 -m pytest tests/ -x -q --tb=short -m "not slow and not hyperframes" 2>&1 | tail -3
```

Expected: `OK` and all tests passing.

---

## Task 1: Filter Parameter Bounds (`video_filter` / `apply_filter`)

**Files:**
- Create: `mcp_video/filter_guardrails.py`
- Modify: `mcp_video/engine_filters.py`
- Test: `tests/test_filter_guardrails.py`

**Why:** Most filter numeric parameters are unbounded. Users can pass `blur radius=1000` or `brightness=10.0` and get garbage.

**Step 1: Write the guardrail module**

Create `mcp_video/filter_guardrails.py`:

```python
"""Parameter bounds validation for video/audio filters."""

from __future__ import annotations

from .errors import MCPVideoError

# Per-filter parameter bounds: (min, max)
_FILTER_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "blur": {"radius": (0.0, 50.0), "strength": (0.0, 5.0)},
    "brightness": {"level": (-1.0, 1.0)},
    "contrast": {"level": (0.0, 3.0)},
    "saturation": {"level": (0.0, 3.0)},
    "grayscale": {},
    "sharpen": {"amount": (0.0, 3.0)},
    "denoise": {"strength": (0.0, 30.0)},
    "vignette": {"intensity": (0.0, 1.0)},
    "ken_burns": {"zoom_speed": (0.0001, 0.01)},
    "reverb": {"in_gain": (0.0, 1.0), "decay": (0.0, 0.9)},
    "compressor": {"ratio": (1.0, 20.0)},
    "noise_reduction": {"noise_level": (0.0, 30.0)},
    "lowpass": {"frequency": (20.0, 20000.0)},
    "highpass": {"frequency": (20.0, 20000.0)},
}


def validate_filter_params(filter_type: str, params: dict[str, float]) -> list[str]:
    """Validate filter parameters against known bounds.

    Returns a list of warning/error messages. Empty list means clean.
    """
    warnings: list[str] = []
    bounds = _FILTER_BOUNDS.get(filter_type)
    if not bounds:
        return warnings

    for key, (lo, hi) in bounds.items():
        value = params.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            warnings.append(f"Parameter '{key}' must be numeric, got {type(value).__name__}")
            continue
        if value < lo or value > hi:
            warnings.append(
                f"Parameter '{key}'={value} is outside recommended range [{lo}, {hi}] "
                f"for filter '{filter_type}'. This may produce unusable output."
            )
    return warnings


def clamp_filter_params(filter_type: str, params: dict[str, float]) -> dict[str, float]:
    """Clamp filter parameters to their safe bounds.

    Returns a new dict with clamped values.
    """
    clamped = dict(params)
    bounds = _FILTER_BOUNDS.get(filter_type)
    if not bounds:
        return clamped

    for key, (lo, hi) in bounds.items():
        value = clamped.get(key)
        if isinstance(value, (int, float)):
            clamped[key] = max(lo, min(hi, float(value)))
    return clamped
```

**Step 2: Wire into `engine_filters.py`**

Modify `mcp_video/engine_filters.py`. Find the `apply_filter` function and add validation before the filter runs:

```python
from .filter_guardrails import validate_filter_params, clamp_filter_params
import warnings as _warnings

# In apply_filter(), after parsing params:
    filter_type = ...  # existing
    params = ...  # existing

    # --- Guardrails ---
    param_warnings = validate_filter_params(filter_type, params)
    for w in param_warnings:
        _warnings.warn(f"[FILTER GUARDRAIL] {w}", stacklevel=2)
    params = clamp_filter_params(filter_type, params)
    # --- End guardrails ---
```

**Step 3: Write tests**

Create `tests/test_filter_guardrails.py`:

```python
import pytest

from mcp_video.filter_guardrails import validate_filter_params, clamp_filter_params


class TestValidateFilterParams:
    def test_blur_radius_in_range_clean(self):
        assert validate_filter_params("blur", {"radius": 5.0}) == []

    def test_blur_radius_too_high_warns(self):
        warnings = validate_filter_params("blur", {"radius": 100.0})
        assert any("outside recommended range" in w for w in warnings)

    def test_blur_radius_negative_warns(self):
        warnings = validate_filter_params("blur", {"radius": -1.0})
        assert any("outside recommended range" in w for w in warnings)

    def test_unknown_filter_no_warnings(self):
        assert validate_filter_params("unknown_filter", {"foo": 999}) == []

    def test_brightness_extreme_warns(self):
        warnings = validate_filter_params("brightness", {"level": 10.0})
        assert len(warnings) == 1

    def test_empty_params_clean(self):
        assert validate_filter_params("blur", {}) == []


class TestClampFilterParams:
    def test_blur_radius_clamped_high(self):
        result = clamp_filter_params("blur", {"radius": 100.0})
        assert result["radius"] == 50.0

    def test_blur_radius_clamped_low(self):
        result = clamp_filter_params("blur", {"radius": -5.0})
        assert result["radius"] == 0.0

    def test_unbounded_param_unchanged(self):
        result = clamp_filter_params("unknown", {"x": 999})
        assert result["x"] == 999
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_filter_guardrails.py -v --tb=short
```

Expected: All pass.

**Step 5: Verify no regressions**

```bash
python3 -m pytest tests/ -x -q --tb=short -m "not slow and not hyperframes"
```

**Step 6: Commit**

```bash
git add mcp_video/filter_guardrails.py tests/test_filter_guardrails.py mcp_video/engine_filters.py
git commit -m "feat(guardrails): add per-filter parameter bounds validation and clamping

- New filter_guardrails module with bounds for 14 filter types
- validate_filter_params warns on out-of-range values
- clamp_filter_params silently clamps to safe ranges
- Wired into apply_filter before FFmpeg execution"
```

---

## Task 2: Video Merge Compatibility Guardrails

**Files:**
- Create: `mcp_video/merge_guardrails.py`
- Modify: `mcp_video/engine_merge.py`
- Test: `tests/test_merge_guardrails.py`

**Why:** Merging clips with different resolutions, FPS, or audio presence produces silent bad output.

**Step 1: Write the guardrail module**

Create `mcp_video/merge_guardrails.py`:

```python
"""Pre-merge validation guardrails."""

from __future__ import annotations

from dataclasses import dataclass

from .engine_probe import probe
from .errors import MCPVideoError


@dataclass(frozen=True)
class ClipInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def probe_clips(clips: list[str]) -> list[ClipInfo]:
    """Probe all clips and return structured info."""
    infos: list[ClipInfo] = []
    for path in clips:
        info = probe(path)
        infos.append(
            ClipInfo(
                path=path,
                width=info.width,
                height=info.height,
                fps=info.fps or 30.0,
                duration=info.duration,
                has_audio=info.audio_codec is not None,
            )
        )
    return infos


def validate_merge_compatibility(
    clips: list[str],
    transition_duration: float = 0.0,
) -> list[str]:
    """Validate clips can be merged without silent bad output.

    Returns list of warning messages.
    """
    warnings: list[str] = []
    if len(clips) < 2:
        return warnings

    infos = probe_clips(clips)

    # 1. Check for mixed audio / no-audio
    audio_status = [i.has_audio for i in infos]
    if any(audio_status) and not all(audio_status):
        warnings.append(
            "Merged clips have mixed audio/no-audio. "
            "Clips without audio may cause concat demuxer errors or silent output. "
            "Consider normalizing all clips to the same audio presence."
        )

    # 2. Check resolution mismatch
    resolutions = {(i.width, i.height) for i in infos}
    if len(resolutions) > 1:
        warnings.append(
            f"Clips have different resolutions: {sorted(resolutions)}. "
            "Merge will normalize by re-encoding all clips."
        )

    # 3. Check FPS mismatch
    fps_values = {i.fps for i in infos}
    if len(fps_values) > 1:
        warnings.append(
            f"Clips have different frame rates: {sorted(fps_values)}. "
            "Output may stutter or drop frames."
        )

    # 4. Check duration vs transition
    if transition_duration > 0:
        min_dur = min(i.duration for i in infos)
        if transition_duration >= min_dur:
            raise MCPVideoError(
                f"transition_duration ({transition_duration}s) must be less than "
                f"the shortest clip duration ({min_dur:.2f}s).",
                error_type="validation_error",
                code="transition_too_long",
            )
        if transition_duration > min_dur * 0.5:
            warnings.append(
                f"transition_duration ({transition_duration}s) is >50% of the shortest "
                f"clip ({min_dur:.2f}s). The transition may dominate the visual."
            )

    # 5. Check for zero-duration clips
    for info in infos:
        if info.duration <= 0:
            raise MCPVideoError(
                f"Clip '{info.path}' has zero or negative duration ({info.duration}).",
                error_type="validation_error",
                code="invalid_duration",
            )

    return warnings
```

**Step 2: Wire into `engine_merge.py`**

Modify `mcp_video/engine_merge.py`. In `merge()`, before calling `_merge_with_transitions` or `_merge_without_transitions`, add:

```python
from .merge_guardrails import validate_merge_compatibility
import warnings as _warnings

# In merge(), after parsing args:
    if len(clips) > 1:
        try:
            merge_warnings = validate_merge_compatibility(
                clips,
                transition_duration=transition_duration or 0.0,
            )
            for w in merge_warnings:
                _warnings.warn(f"[MERGE GUARDRAIL] {w}", stacklevel=2)
        except MCPVideoError:
            raise
        except Exception as e:
            _warnings.warn(f"[MERGE GUARDRAIL] Could not validate merge compatibility: {e}", stacklevel=2)
```

**Step 3: Write tests**

Create `tests/test_merge_guardrails.py`:

```python
import pytest

from mcp_video.merge_guardrails import validate_merge_compatibility, ClipInfo
from mcp_video.errors import MCPVideoError


class TestValidateMergeCompatibility:
    def test_single_clip_no_warnings(self, sample_video):
        assert validate_merge_compatibility([sample_video]) == []

    def test_identical_clips_no_warnings(self, sample_video):
        assert validate_merge_compatibility([sample_video, sample_video]) == []

    def test_transition_too_long_raises(self, sample_video):
        with pytest.raises(MCPVideoError, match="transition_duration"):
            validate_merge_compatibility(
                [sample_video, sample_video],
                transition_duration=999.0,
            )

    def test_transition_half_duration_warns(self, sample_video):
        info = ...  # probe sample_video for duration
        # This test needs actual fixture access
        pass
```

Note: For tests that need actual video probing, use the existing `sample_video` fixture from `conftest.py`.

**Step 4-6:** Same pattern as Task 1 — run tests, verify no regressions, commit.

---

## Task 3: Audio Mixing Guardrails

**Files:**
- Create: `mcp_video/audio_guardrails.py`
- Modify: `mcp_video/engine_audio_ops.py`
- Test: `tests/test_audio_guardrails.py`

**Why:** Sample rate mismatches, volume clipping, and phase cancellation produce bad audio silently.

**Step 1: Write the guardrail module**

Create `mcp_video/audio_guardrails.py`:

```python
"""Audio mixing and overlay guardrails."""

from __future__ import annotations

from .engine_probe import probe
from .errors import MCPVideoError


def probe_audio_stream(path: str) -> dict[str, float | int] | None:
    """Probe audio stream properties. Returns None if no audio."""
    info = probe(path)
    if info.audio_codec is None:
        return None
    return {
        "sample_rate": info.sample_rate or 48000,
        "channels": info.audio_channels or 2,
        "duration": info.duration,
    }


def validate_audio_mix(
    source_path: str,
    added_path: str,
    volume: float = 1.0,
    start_time: float = 0.0,
) -> list[str]:
    """Validate audio mix parameters before execution.

    Returns list of warning messages.
    """
    warnings: list[str] = []

    source_audio = probe_audio_stream(source_path)
    added_audio = probe_audio_stream(added_path)

    if source_audio is None and added_audio is None:
        warnings.append("Neither source nor added audio has an audio stream.")
        return warnings

    # 1. Sample rate mismatch
    if source_audio and added_audio:
        if source_audio["sample_rate"] != added_audio["sample_rate"]:
            warnings.append(
                f"Sample rate mismatch: source={source_audio['sample_rate']}Hz, "
                f"added={added_audio['sample_rate']}Hz. "
                f"FFmpeg will resample but quality may degrade."
            )

    # 2. Channel count mismatch
    if source_audio and added_audio:
        if source_audio["channels"] != added_audio["channels"]:
            warnings.append(
                f"Channel count mismatch: source={source_audio['channels']}, "
                f"added={added_audio['channels']}. "
                f"Channels may be collapsed unpredictably."
            )

    # 3. Volume clipping risk
    if volume > 1.0:
        warnings.append(
            f"volume={volume} > 1.0. If source audio is already near peak, "
            f"this may cause digital clipping/distortion."
        )
    if volume < 0.0:
        raise MCPVideoError(
            f"volume must be >= 0, got {volume}",
            error_type="validation_error",
            code="invalid_volume",
        )

    # 4. Start time beyond source duration
    if source_audio and start_time > source_audio["duration"]:
        warnings.append(
            f"start_time={start_time}s exceeds source duration "
            f"({source_audio['duration']:.2f}s). Audio will never play."
        )

    return warnings
```

**Step 2: Wire into `engine_audio_ops.py`**

In `add_audio()`, before building FFmpeg command:

```python
from .audio_guardrails import validate_audio_mix
import warnings as _warnings

# After parsing args:
    mix_warnings = validate_audio_mix(
        video_path, audio_path, volume=volume, start_time=start_time or 0.0
    )
    for w in mix_warnings:
        _warnings.warn(f"[AUDIO GUARDRAIL] {w}", stacklevel=2)
```

**Step 3: Write tests**

Create `tests/test_audio_guardrails.py`:

```python
import pytest

from mcp_video.audio_guardrails import validate_audio_mix
from mcp_video.errors import MCPVideoError


class TestValidateAudioMix:
    def test_same_file_no_warnings(self, sample_video):
        # A video mixed with itself should have matching audio props
        warnings = validate_audio_mix(sample_video, sample_video, volume=1.0)
        # May still warn about volume if near peak — just check no exception
        assert isinstance(warnings, list)

    def test_negative_volume_raises(self, sample_video):
        with pytest.raises(MCPVideoError, match="volume must be >= 0"):
            validate_audio_mix(sample_video, sample_video, volume=-0.5)

    def test_high_volume_warns(self, sample_video):
        warnings = validate_audio_mix(sample_video, sample_video, volume=2.0)
        assert any("clipping" in w.lower() for w in warnings)
```

**Step 4-6:** Run tests, verify regressions, commit.

---

## Task 4: Overlay / Watermark / Chroma Key Bounds

**Files:**
- Modify: `mcp_video/engine_overlay.py`
- Modify: `mcp_video/engine_watermark.py`
- Modify: `mcp_video/engine_chroma_key.py`
- Modify: `mcp_video/validation.py` (add `_validate_opacity` if not present)
- Test: `tests/test_overlay_guardrails.py`

**Why:** These three components share the same failure modes — unbounded opacity, timing beyond video duration, size mismatches.

**Step 1: Add shared validation helpers to `validation.py`**

Add to `mcp_video/validation.py`:

```python
def _validate_opacity(value: float, name: str = "opacity") -> float:
    """Validate opacity is in [0.0, 1.0]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise MCPVideoError(
            f"{name} must be a number, got {type(value).__name__}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if f < 0.0 or f > 1.0:
        raise MCPVideoError(
            f"{name} must be between 0.0 and 1.0, got {f}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return f


def _validate_timing_against_duration(
    start_time: float | None,
    duration: float | None,
    video_duration: float,
) -> list[str]:
    """Validate timing parameters against video duration.

    Returns list of warnings.
    """
    warnings: list[str] = []
    if start_time is not None and start_time > video_duration:
        warnings.append(
            f"start_time={start_time}s exceeds video duration "
            f"({video_duration:.2f}s). Overlay will never appear."
        )
    if start_time is not None and duration is not None:
        end = start_time + duration
        if end > video_duration:
            warnings.append(
                f"Overlay ends at {end:.2f}s, past video duration "
                f"({video_duration:.2f}s). It will disappear early."
            )
    return warnings
```

**Step 2: Wire into `engine_overlay.py`**

In `overlay_video()`, after parsing args:

```python
from .validation import _validate_opacity, _validate_timing_against_duration
from .engine_probe import probe
import warnings as _warnings

# After parsing args:
    _validate_opacity(opacity)
    try:
        bg_info = probe(background_path)
        timing_warnings = _validate_timing_against_duration(
            start_time, duration, bg_info.duration
        )
        for w in timing_warnings:
            _warnings.warn(f"[OVERLAY GUARDRAIL] {w}", stacklevel=2)
    except Exception as e:
        _warnings.warn(f"[OVERLAY GUARDRAIL] Could not validate timing: {e}", stacklevel=2)
```

**Step 3: Wire into `engine_watermark.py`**

In `watermark()`, add the same opacity validation:

```python
from .validation import _validate_opacity

# After parsing args:
    _validate_opacity(opacity)
```

**Step 4: Wire into `engine_chroma_key.py`**

In `chroma_key()`, add bounds for `similarity` and `blend`:

```python
# After parsing args:
    if not (0.0 <= similarity <= 1.0):
        raise MCPVideoError(
            f"similarity must be in [0.0, 1.0], got {similarity}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not (0.0 <= blend <= 1.0):
        raise MCPVideoError(
            f"blend must be in [0.0, 1.0], got {blend}",
            error_type="validation_error",
            code="invalid_parameter",
        )
```

**Step 5: Write tests**

Create `tests/test_overlay_guardrails.py`:

```python
import pytest

from mcp_video.validation import _validate_opacity, _validate_timing_against_duration
from mcp_video.errors import MCPVideoError


class TestValidateOpacity:
    def test_valid_opacity(self):
        assert _validate_opacity(0.5) == 0.5

    def test_opacity_zero(self):
        assert _validate_opacity(0.0) == 0.0

    def test_opacity_one(self):
        assert _validate_opacity(1.0) == 1.0

    def test_opacity_negative_raises(self):
        with pytest.raises(MCPVideoError, match="between 0.0 and 1.0"):
            _validate_opacity(-0.1)

    def test_opacity_over_one_raises(self):
        with pytest.raises(MCPVideoError, match="between 0.0 and 1.0"):
            _validate_opacity(1.5)


class TestValidateTiming:
    def test_clean_timing(self):
        assert _validate_timing_against_duration(0.5, 1.0, 5.0) == []

    def test_start_past_end_warns(self):
        warnings = _validate_timing_against_duration(10.0, 1.0, 5.0)
        assert any("never appear" in w for w in warnings)

    def test_end_past_duration_warns(self):
        warnings = _validate_timing_against_duration(0.0, 10.0, 5.0)
        assert any("disappear early" in w for w in warnings)
```

**Step 6-8:** Run tests, verify regressions, commit.

---

## Task 5: Animated Text Timing Guardrails

**Files:**
- Modify: `mcp_video/effects_engine/text.py`
- Modify: `mcp_video/validation.py` (add `_validate_color` call)
- Test: `tests/test_effects_engine.py` (append tests)

**Why:** Text can start after video ends, overflow screen, or use invalid colors.

**Step 1: Add timing and overflow validation to `text_animated`**

In `mcp_video/effects_engine/text.py`, in `text_animated()`, after parsing args:

```python
from ..validation import _validate_color
from ..engine_probe import probe
import warnings as _warnings

# After parsing args, before building filter:
    # Validate color
    _validate_color(color)

    # Probe video for timing validation
    try:
        video_info = probe(video)
        if start < 0:
            raise MCPVideoError(
                f"start must be >= 0, got {start}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if duration is not None and duration <= 0:
            raise MCPVideoError(
                f"duration must be > 0, got {duration}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if start > video_info.duration:
            _warnings.warn(
                f"[TEXT GUARDRAIL] start={start}s exceeds video duration "
                f"({video_info.duration:.2f}s). Text will never appear.",
                stacklevel=2,
            )
        if duration is not None and start + duration > video_info.duration:
            _warnings.warn(
                f"[TEXT GUARDRAIL] Text ends at {start + duration:.2f}s, past "
                f"video duration ({video_info.duration:.2f}s). It will disappear early.",
                stacklevel=2,
            )

        # Text overflow check
        text_w, text_h = _measure_text(text, font_path, size)
        if text_w > video_info.width - 40 or text_h > video_info.height - 40:
            _warnings.warn(
                f"[TEXT GUARDRAIL] Text dimensions ({text_w}x{text_h}) may exceed "
                f"video frame ({video_info.width}x{video_info.height}). "
                f"Consider reducing font size or shortening text.",
                stacklevel=2,
            )
    except MCPVideoError:
        raise
    except Exception as e:
        _warnings.warn(f"[TEXT GUARDRAIL] Could not validate text layout: {e}", stacklevel=2)
```

**Step 2: Write tests**

Append to existing `tests/test_effects_engine.py`:

```python
class TestTextAnimatedGuardrails:
    def test_text_color_validated(self):
        with pytest.raises(MCPVideoError):
            text_animated(
                "sample.mp4",  # needs actual video fixture
                text="Hello",
                color="red;eq=brightness=10",
            )

    def test_negative_start_raises(self, sample_video):
        with pytest.raises(MCPVideoError, match="start must be >= 0"):
            text_animated(sample_video, text="Hello", start=-1.0)
```

Note: These tests require the `sample_video` fixture.

**Step 3-5:** Run tests, verify regressions, commit.

---

## Task 6: Grid Layout + Split Screen Guardrails

**Files:**
- Modify: `mcp_video/effects_engine/layout.py`
- Modify: `mcp_video/engine_split_screen.py`
- Test: `tests/test_layout_guardrails.py`

**Why:** Clips silently dropped in grids. Audio lost in split screen. Duration mismatches truncated.

**Step 1: Add clip count and duration checks to `layout_grid`**

In `mcp_video/effects_engine/layout.py`, in `layout_grid()`, after parsing `layout`:

```python
import warnings as _warnings
from ..engine_probe import probe

# After layout is parsed:
    rows, cols = ...  # existing
    n_cells = rows * cols
    if len(clips) > n_cells:
        _warnings.warn(
            f"[GRID GUARDRAIL] {len(clips)} clips provided but {layout} only has "
            f"{n_cells} cells. Only the first {n_cells} clips will be used.",
            stacklevel=2,
        )

    # Duration check
    try:
        durations = [probe(c).duration for c in clips[:n_cells]]
        min_dur = min(durations)
        max_dur = max(durations)
        if max_dur - min_dur > 1.0:
            _warnings.warn(
                f"[GRID GUARDRAIL] Clip durations vary from {min_dur:.1f}s to "
                f"{max_dur:.1f}s. Output will be truncated to shortest clip.",
                stacklevel=2,
            )
    except Exception:
        pass
```

**Step 2: Add audio and duration checks to `split_screen`**

In `mcp_video/engine_split_screen.py`, in `split_screen()`, after probing:

```python
import warnings as _warnings

# After probing both videos:
    # Check durations
    if abs(left_info.duration - right_info.duration) > 1.0:
        _warnings.warn(
            f"[SPLIT GUARDRAIL] Input durations differ significantly: "
            f"left={left_info.duration:.1f}s, right={right_info.duration:.1f}s. "
            f"Output will be truncated to the shorter.",
            stacklevel=2,
        )

    # Check FPS
    if left_info.fps and right_info.fps and abs(left_info.fps - right_info.fps) > 1.0:
        _warnings.warn(
            f"[SPLIT GUARDRAIL] Input frame rates differ: "
            f"left={left_info.fps:.1f}fps, right={right_info.fps:.1f}fps. "
            f"Output may stutter.",
            stacklevel=2,
        )

    # Check audio
    left_has_audio = left_info.audio_codec is not None
    right_has_audio = right_info.audio_codec is not None
    if right_has_audio and not left_has_audio:
        _warnings.warn(
            "[SPLIT GUARDRAIL] Right video has audio but left does not. "
            "Only left audio is mapped; right audio will be lost.",
            stacklevel=2,
        )
```

**Step 3: Write tests**

Create `tests/test_layout_guardrails.py`:

```python
import pytest

from mcp_video.effects_engine.layout import layout_grid
from mcp_video.engine_split_screen import split_screen


class TestLayoutGridGuardrails:
    @pytest.mark.skip("Requires multiple video fixtures")
    def test_excess_clips_warns(self):
        pass


class TestSplitScreenGuardrails:
    @pytest.mark.skip("Requires two video fixtures with different durations")
    def test_duration_mismatch_warns(self):
        pass
```

These tests are harder to write without specific fixture data. Use `@pytest.mark.skip` for now and test manually with real videos.

**Step 4-6:** Run tests, verify regressions, commit.

---

## Final Verification Checklist

After all tasks complete, run the full test suite:

```bash
python3 -m pytest tests/ -x -q --tb=short -m "not slow and not hyperframes"
```

Expected: All tests pass, no new warnings from existing tests.

Then verify imports:

```bash
python3 -c "import mcp_video; print('Import OK')"
```

Then run the public surface test to ensure tool count is still correct:

```bash
python3 -m pytest tests/test_public_surface.py -v --tb=short
```

---

## Files Created Summary

| File | Purpose |
|------|---------|
| `mcp_video/filter_guardrails.py` | Per-filter parameter bounds |
| `mcp_video/merge_guardrails.py` | Pre-merge compatibility checks |
| `mcp_video/audio_guardrails.py` | Audio mix validation |
| `tests/test_filter_guardrails.py` | Filter bounds tests |
| `tests/test_merge_guardrails.py` | Merge guardrail tests |
| `tests/test_audio_guardrails.py` | Audio guardrail tests |
| `tests/test_overlay_guardrails.py` | Overlay/watermark/chroma tests |
| `tests/test_layout_guardrails.py` | Grid/split screen tests |

## Files Modified Summary

| File | Changes |
|------|---------|
| `mcp_video/validation.py` | Add `_validate_opacity`, `_validate_timing_against_duration` |
| `mcp_video/engine_filters.py` | Wire filter guardrails |
| `mcp_video/engine_merge.py` | Wire merge guardrails |
| `mcp_video/engine_audio_ops.py` | Wire audio guardrails |
| `mcp_video/engine_overlay.py` | Add opacity + timing validation |
| `mcp_video/engine_watermark.py` | Add opacity validation |
| `mcp_video/engine_chroma_key.py` | Add similarity/blend bounds |
| `mcp_video/effects_engine/text.py` | Add timing + overflow + color validation |
| `mcp_video/effects_engine/layout.py` | Add clip count + duration warnings |
| `mcp_video/engine_split_screen.py` | Add duration/FPS/audio warnings |
