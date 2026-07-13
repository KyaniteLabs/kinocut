"""Tunable runtime defaults for ``kinocut_sound``.

Default values for parameters that a deployment or plan may reasonably adjust.
These are NOT validation ceilings (see :mod:`kinocut_sound.limits`) or regex
patterns (see :mod:`kinocut_sound.validation`).

Nothing in this module imports from ``kinocut`` runtime or from other
``kinocut_sound`` contract modules, so it is safe to import from any layer.
"""

from __future__ import annotations

# --- Timeline ---

# Gap tolerance (seconds): cues must not open gaps larger than this without
# explanation. Design: cue/master sync tolerance 10 ms.
DEFAULT_GAP_TOLERANCE_SECONDS: float = 0.010

# Declared tail (seconds) after the last cue. Zero is the natural default.
DEFAULT_TAIL_SECONDS: float = 0.0

# --- Delivery loudness ---

# Default loudness tolerance (LU) for delivery loudness targets.
DEFAULT_LOUDNESS_TOLERANCE_LU: float = 1.0

# Default true-peak ceilings by delivery class (dBTP). Stream/podcast use
# -1.0; broadcast (EBU R128 / ATSC A85) uses -2.0.
DEFAULT_STREAM_PODCAST_TRUE_PEAK_DBTP: float = -1.0
DEFAULT_BROADCAST_TRUE_PEAK_DBTP: float = -2.0

# --- Capability ---

# Default adapter call timeout (seconds). Design: 60 s baseline.
DEFAULT_ADAPTER_TIMEOUT_SECONDS: float = 60.0

# --- Routing ---

# Default pan position (centre) and static gain defaults.
DEFAULT_PAN_POSITION: float = 0.0
DEFAULT_BUS_GAIN_DB: float = 0.0
DEFAULT_SEND_GAIN_DB: float = -6.0

# Default latency-compensation residual (samples): fully compensated.
DEFAULT_LATENCY_RESIDUAL_SAMPLES: int = 0

# --- Lines / Prosody ---

# Default prosody overrides: neutral rate, pitch, volume, and emphasis.
DEFAULT_PROSODY_RATE: float = 1.0
DEFAULT_PROSODY_PITCH_SEMITONES: float = 0.0
DEFAULT_PROSODY_VOLUME_DB: float = 0.0
DEFAULT_PROSODY_EMPHASIS: float = 0.0
