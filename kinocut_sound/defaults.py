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

# --- Provider execution policy ---

DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 5.0
DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS: float = 30.0
DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS: float = 60.0
DEFAULT_PROVIDER_MAX_RETRIES: int = 2
DEFAULT_PROVIDER_MAX_CONCURRENCY: int = 2
DEFAULT_PROVIDER_RATE_LIMIT_PER_MINUTE: int = 30
DEFAULT_PROVIDER_MAX_INPUT_BYTES: int = 268_435_456
DEFAULT_PROVIDER_MAX_OUTPUT_BYTES: int = 536_870_912
DEFAULT_PROVIDER_MAX_DURATION_SECONDS: float = 3600.0

# --- Routing ---

# Default pan position (centre) and static gain defaults.
DEFAULT_PAN_POSITION: float = 0.0
DEFAULT_BUS_GAIN_DB: float = 0.0
DEFAULT_SEND_GAIN_DB: float = -6.0
DEFAULT_SEND_POST_FADER: bool = True
DEFAULT_LAYER_DUCKING_ATTENUATION_DB = 9.0
DEFAULT_LAYER_DUCKING_ATTACK_MS = 80.0
DEFAULT_LAYER_DUCKING_RELEASE_MS = 350.0
DEFAULT_LAYER_DUCKING_RECOVERY_MS = 500.0

# Default latency-compensation residual (samples): fully compensated.
DEFAULT_LATENCY_RESIDUAL_SAMPLES: int = 0

# --- Lines / Prosody ---

# Default prosody overrides: neutral rate, pitch, volume, and emphasis.
DEFAULT_PROSODY_RATE: float = 1.0
DEFAULT_PROSODY_PITCH_SEMITONES: float = 0.0
DEFAULT_PROSODY_VOLUME_DB: float = 0.0
DEFAULT_PROSODY_EMPHASIS: float = 0.0

DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS = 300.0
DEFAULT_DUB_UTTERANCE_TIMEOUT_SECONDS = 10.0
DEFAULT_DUB_TOTAL_TIMEOUT_SECONDS = 120.0
DEFAULT_DUB_WORDS_PER_MINUTE = 175
DEFAULT_DUB_AMPLITUDE = 100
DEFAULT_DUB_SAMPLE_RATE_HZ = 22050
DEFAULT_PUBLIC_MIX_STEMS = ("dialogue", "ambience", "sfx")
DEFAULT_LOUDNESS_METER_TIMEOUT_SECONDS = 60.0
DEFAULT_LOUDNESS_VERSION_TIMEOUT_SECONDS = 2.0
DEFAULT_LOUDNESS_DEMO_DURATION_SECONDS = 10.0
DEFAULT_MASTER_TOTAL_TIMEOUT_SECONDS = 180.0
DEFAULT_MASTER_PEAK_MARGIN_DB = 0.2
DEFAULT_MASTER_LRA_LU = 11.0
DEFAULT_MASTER_LIMITER_ATTACK_MS = 5.0
DEFAULT_MASTER_LIMITER_RELEASE_MS = 50.0
DEFAULT_MIX_CHANNEL_COUNT = 1
DEFAULT_MIX_SAMPLE_RATE_HZ = 22050
DEFAULT_MIX_DUCK_ATTENUATION_DB = 12.0
DEFAULT_MIX_DUCK_ATTACK_MS = 20.0
DEFAULT_MIX_DUCK_RELEASE_MS = 200.0
DEFAULT_MIX_DUCK_THRESHOLD = 0.02
DEFAULT_ASR_TOTAL_TIMEOUT_SECONDS = 180.0
DEFAULT_ASR_PROBE_TIMEOUT_SECONDS = 10.0
DEFAULT_ASR_THREADS = 2
DEFAULT_ASR_SAMPLE_RATE_HZ = 16000
DEFAULT_ASR_DECODE = {
    "task": "transcribe",
    "fp16": False,
    "temperature": 0,
    "verbose": None,
    "beam_size": 1,
    "best_of": None,
    "condition_on_previous_text": False,
    "compression_ratio_threshold": 2.4,
    "logprob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "initial_prompt": None,
    "carry_initial_prompt": False,
    "word_timestamps": False,
    "clip_timestamps": "0",
    "hallucination_silence_threshold": None,
    "suppress_tokens": "-1",
    "suppress_blank": True,
    "without_timestamps": False,
    "max_initial_timestamp": 1.0,
    "patience": None,
    "length_penalty": None,
    "prompt": None,
    "prefix": None,
}
