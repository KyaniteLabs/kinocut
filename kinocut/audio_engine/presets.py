"""Audio preset definitions and helpers."""

from __future__ import annotations

import copy

_PITCH_MULT = {"low": 0.7, "mid": 1.0, "high": 1.5}

_PRESETS: dict[str, dict] = {
    # UI Sounds — crisp, short, modern
    "ui-blip": {
        "waveform": "sine",
        "frequency": 880,
        "duration": 0.08,
        "volume": 0.4,
        "effects": {
            "envelope": {"attack": 0.001, "decay": 0.04, "sustain": 0, "release": 0.02},
            "reverb": {"room_size": 0.3, "damping": 0.5, "wet_level": 0.15},
        },
    },
    "ui-click": {
        "waveform": "pulse",
        "frequency": 600,
        "duration": 0.04,
        "volume": 0.25,
        "effects": {
            "lowpass": 3000,
            "envelope": {"attack": 0.001, "decay": 0.015, "sustain": 0, "release": 0.01},
        },
    },
    "ui-tap": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.03,
        "volume": 0.2,
        "effects": {"lowpass": 5000, "fade_out": 0.02},
    },
    "ui-whoosh-up": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.35,
        "volume": 0.3,
        "effects": {
            "lowpass": {"frequency": 200, "type": "sweep_up"},
            "fade_in": 0.05,
            "fade_out": 0.1,
        },
    },
    "ui-whoosh-down": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.35,
        "volume": 0.3,
        "effects": {
            "lowpass": {"frequency": 4000, "type": "sweep_down"},
            "fade_in": 0.05,
            "fade_out": 0.1,
        },
    },
    # Ambient — rich, layered, cinematic
    "drone-low": {
        "waveform": "supersaw",
        "frequency": 65,
        "duration": 5.0,
        "volume": 0.3,
        "effects": {
            "reverb": {"room_size": 0.85, "damping": 0.2, "wet_level": 0.45},
            "lowpass": 800,
            "chorus": {"rate": 0.3, "depth": 0.003, "mix": 0.4},
        },
    },
    "drone-mid": {
        "waveform": "fm",
        "frequency": 130,
        "duration": 5.0,
        "volume": 0.25,
        "effects": {
            "reverb": {"room_size": 0.7, "damping": 0.3, "wet_level": 0.35},
            "vibrato": {"rate": 3.0, "depth": 0.002},
            "chorus": {"rate": 0.5, "depth": 0.002, "mix": 0.3},
        },
    },
    "drone-tech": {
        "waveform": "pulse",
        "frequency": 110,
        "duration": 5.0,
        "volume": 0.2,
        "effects": {
            "lowpass": 600,
            "reverb": {"room_size": 0.5, "damping": 0.5, "wet_level": 0.3},
            "delay": {"delay_time": 0.25, "feedback": 0.3, "mix": 0.2},
            "distortion": {"drive": 0.3, "type": "bit"},
        },
    },
    "drone-ominous": {
        "waveform": "supersaw",
        "frequency": 55,
        "duration": 5.0,
        "volume": 0.35,
        "effects": {
            "lowpass": 400,
            "reverb": {"room_size": 0.95, "damping": 0.15, "wet_level": 0.55},
            "chorus": {"rate": 0.2, "depth": 0.005, "mix": 0.5},
        },
    },
    # Notifications — musical, pleasant
    "chime-success": {
        "waveform": "fm",
        "frequency": 523.25,
        "duration": 0.6,
        "volume": 0.35,
        "effects": {
            "envelope": {"attack": 0.005, "decay": 0.08, "sustain": 0.5, "release": 0.4},
            "reverb": {"room_size": 0.5, "damping": 0.4, "wet_level": 0.25},
            "delay": {"delay_time": 0.12, "feedback": 0.2, "mix": 0.15},
        },
    },
    "chime-error": {
        "waveform": "supersaw",
        "frequency": 180,
        "duration": 0.35,
        "volume": 0.3,
        "effects": {
            "envelope": {"attack": 0.005, "decay": 0.1, "sustain": 0.2, "release": 0.15},
            "lowpass": 1200,
            "distortion": {"drive": 0.4, "type": "soft"},
        },
    },
    "chime-notification": {
        "waveform": "fm",
        "frequency": 659.25,
        "duration": 0.35,
        "volume": 0.3,
        "effects": {
            "envelope": {"attack": 0.005, "decay": 0.06, "sustain": 0.3, "release": 0.25},
            "reverb": {"room_size": 0.3, "damping": 0.5, "wet_level": 0.2},
        },
    },
    # Percussion / FX
    "bass-kick": {
        "waveform": "sine",
        "frequency": 60,
        "duration": 0.15,
        "volume": 0.6,
        "effects": {
            "envelope": {"attack": 0.001, "decay": 0.08, "sustain": 0, "release": 0.05},
            "distortion": {"drive": 0.2, "type": "soft"},
        },
    },
    "snare": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.12,
        "volume": 0.4,
        "effects": {
            "highpass": 800,
            "envelope": {"attack": 0.001, "decay": 0.06, "sustain": 0, "release": 0.03},
            "reverb": {"room_size": 0.4, "damping": 0.5, "wet_level": 0.1},
        },
    },
    "hi-hat": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.05,
        "volume": 0.25,
        "effects": {
            "highpass": 8000,
            "envelope": {"attack": 0.001, "decay": 0.02, "sustain": 0, "release": 0.01},
        },
    },
    "alarm": {
        "waveform": "square",
        "frequency": 800,
        "duration": 1.0,
        "volume": 0.4,
        "effects": {
            "tremolo": {"rate": 8.0, "depth": 0.8},
            "distortion": {"drive": 0.3, "type": "soft"},
        },
    },
    "notify": {
        "waveform": "pluck",
        "frequency": 440,
        "duration": 0.4,
        "volume": 0.35,
        "effects": {
            "reverb": {"room_size": 0.4, "damping": 0.5, "wet_level": 0.2},
            "delay": {"delay_time": 0.15, "feedback": 0.15, "mix": 0.2},
        },
    },
    "confirm": {
        "waveform": "sine",
        "frequency": 784,
        "duration": 0.15,
        "volume": 0.35,
        "effects": {
            "envelope": {"attack": 0.001, "decay": 0.05, "sustain": 0, "release": 0.08},
            "reverb": {"room_size": 0.3, "damping": 0.5, "wet_level": 0.15},
        },
    },
    "cancel": {
        "waveform": "sine",
        "frequency": 330,
        "duration": 0.2,
        "volume": 0.3,
        "effects": {
            "envelope": {"attack": 0.001, "decay": 0.08, "sustain": 0, "release": 0.1},
            "lowpass": 2000,
        },
    },
    # Data Sounds
    "typing": {
        "waveform": "noise",
        "frequency": 440.0,
        "duration": 0.08,
        "volume": 0.12,
        "effects": {"lowpass": 5000, "fade_out": 0.04},
    },
    "scan": {
        "waveform": "sine",
        "frequency": 1200,
        "duration": 0.8,
        "volume": 0.18,
        "effects": {
            "lowpass": 3000,
            "vibrato": {"rate": 10.0, "depth": 0.001},
        },
    },
    "processing": {
        "waveform": "pulse",
        "frequency": 90,
        "duration": 2.0,
        "volume": 0.15,
        "effects": {
            "lowpass": 500,
            "reverb": {"room_size": 0.3, "damping": 0.6, "wet_level": 0.2},
            "chorus": {"rate": 0.4, "depth": 0.002, "mix": 0.3},
        },
    },
    "data-flow": {
        "waveform": "fm",
        "frequency": 220,
        "duration": 0.6,
        "volume": 0.25,
        "effects": {
            "fade_in": 0.1,
            "fade_out": 0.2,
            "reverb": {"room_size": 0.3, "damping": 0.5, "wet_level": 0.2},
            "delay": {"delay_time": 0.1, "feedback": 0.2, "mix": 0.15},
        },
    },
    "upload": {
        "waveform": "sine",
        "frequency": 880,
        "duration": 0.6,
        "volume": 0.3,
        "effects": {
            "envelope": {"attack": 0.005, "decay": 0.2, "sustain": 0.1, "release": 0.2},
            "delay": {"delay_time": 0.08, "feedback": 0.15, "mix": 0.2},
        },
    },
    "download": {
        "waveform": "sine",
        "frequency": 660,
        "duration": 0.6,
        "volume": 0.3,
        "effects": {
            "envelope": {"attack": 0.005, "decay": 0.2, "sustain": 0.1, "release": 0.2},
            "delay": {"delay_time": 0.08, "feedback": 0.15, "mix": 0.2},
        },
    },
}


def list_presets() -> list[str]:
    """Return a sorted list of available audio preset names."""
    return sorted(_PRESETS.keys())


def get_preset_config(name: str) -> dict:
    """Return a deep copy of the configuration dict for the given preset.

    Raises:
        KeyError: If the preset name is not recognized.
    """
    if name not in _PRESETS:
        raise KeyError(f"Unknown preset: {name}. Available: {list_presets()}")
    return copy.deepcopy(_PRESETS[name])
