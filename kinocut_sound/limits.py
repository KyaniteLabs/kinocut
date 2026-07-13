"""Resource ceilings and hard bounds for ``kinocut_sound``.

Maximum/minimum bounds that protect against resource exhaustion and enforce
design ceilings. Centralising them here keeps magic numbers out of contract
modules and makes the ceiling surface auditable in one place.

Nothing in this module imports from ``kinocut`` runtime or from other
``kinocut_sound`` contract modules, so it is safe to import from any layer.
"""

from __future__ import annotations

# --- Time / duration floors ---
# All time-valued fields (start, in/out points, tail, probed duration, output
# duration) must be non-negative. Durations are strictly positive via ``gt``.
MIN_TIME_SECONDS: float = 0.0

# --- Gain (dB) envelope ---
MIN_GAIN_DB: float = -120.0
MAX_GAIN_DB: float = 12.0

# --- Pan position envelope ---
MIN_PAN_POSITION: float = -1.0
MAX_PAN_POSITION: float = 1.0

# --- Ducking sidechain envelope ---
MIN_DUCKING_ATTENUATION_DB: float = 0.0  # gt: strictly positive attenuation
MAX_DUCKING_ATTENUATION_DB: float = 24.0
MIN_DUCKING_TIME_MS: float = 0.0         # gt: strictly positive time
MAX_DUCKING_ATTACK_MS: float = 1000.0
MAX_DUCKING_RELEASE_MS: float = 5000.0
MAX_DUCKING_RECOVERY_MS: float = 10000.0

# --- Prosody envelope ---
MIN_PROSODY_RATE: float = 0.0            # gt: strictly positive
MAX_PROSODY_RATE: float = 2.0
MIN_PROSODY_PITCH_SEMITONES: float = -12.0
MAX_PROSODY_PITCH_SEMITONES: float = 12.0  # lt: exclusive ceiling
MIN_PROSODY_VOLUME_DB: float = -24.0
MAX_PROSODY_VOLUME_DB: float = 12.0

# --- Normalized levels (emphasis, intensity) ---
MIN_NORMALIZED_LEVEL: float = 0.0
MAX_NORMALIZED_LEVEL: float = 1.0

# --- Loudness verification (receipt) ---
MAX_LOUDNESS_LUFS: float = 0.0           # lt: must be negative
MAX_TRUE_PEAK_DBTP: float = 0.0          # lt: must be negative
MIN_LOUDNESS_RANGE_LU: float = 0.0       # ge: LRA floor
MAX_LOUDNESS_RANGE_LU: float = 24.0      # le: LRA ceiling

# --- Loudness target (delivery) ---
MIN_LOUDNESS_TOLERANCE_LU: float = 0.0   # gt: strictly positive
MAX_LOUDNESS_TOLERANCE_LU: float = 2.0

# --- Versioning / identity ---
MIN_VERSION: int = 1                     # ge: positive integer versions

# --- Text length ---
MIN_TEXT_LENGTH_CHARS: int = 0           # ge: non-negative character count

# --- Standalone script resource ceilings ---
MAX_SCRIPT_ACTORS: int = 256
MAX_SCRIPT_SCENES: int = 512
MAX_SCRIPT_LINES_PER_SCENE: int = 2048
MAX_SCRIPT_BEATS_PER_SCENE: int = 2048
MAX_SCRIPT_TURNS_PER_SCENE: int = 4096
MAX_SCRIPT_EVENTS_PER_SCENE: int = 4096
MAX_SCRIPT_TEXT_LENGTH_CHARS: int = 20_000
MAX_SCRIPT_NAME_LENGTH_CHARS: int = 256

# --- Pure episode-assembly input ceilings ---
MAX_ASSEMBLY_CLIPS: int = 4096
MAX_ASSEMBLY_FOLEY_INTENTS: int = 4096
MAX_ASSEMBLY_SILENCE_INTENTS: int = 4096
MAX_ASSEMBLY_TIMELINE_CUES: int = 16_384

# --- Resource floors ---
MIN_RETENTION_DAYS: int = 0              # ge: non-negative retention
MIN_COST_USD: float = 0.0                # ge: non-negative cost
MIN_SAMPLE_RATE_HZ: int = 0              # gt: strictly positive rate

# --- Capability timeout ceiling ---
MAX_ADAPTER_TIMEOUT_SECONDS: float = 600.0

# --- Latency compensation ---
MIN_LATENCY_RESIDUAL_SAMPLES: int = 0
# Maximum latency-compensation residual after compensation (samples).
# Design §"RenderFingerprint & numeric mix policy": at most one sample.
MAX_LATENCY_RESIDUAL_SAMPLES: int = 1

# --- Stem recombination ---
MIN_STEM_RECOMBINATION_TOLERANCE_LSB_24BIT: int = 0
# Maximum stem-recombination tolerance (LSB at 24-bit).
MAX_STEM_RECOMBINATION_TOLERANCE_LSB_24BIT: int = 1
