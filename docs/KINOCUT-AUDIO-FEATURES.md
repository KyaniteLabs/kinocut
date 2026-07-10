# Kinocut Audio Features

This document records the procedural-audio feature design that Kinocut implemented from the original explainer-video work.

---

## 🎯 **Core Audio Engine**

### `Client.audio_synthesize`
Generate audio procedurally using Web Audio API-style synthesis.

```python
from kinocut import Client

video = Client()

# Generate a drone tone
video.audio_synthesize(
    output="drone.wav",
    waveform="sine",  # sine, square, sawtooth, triangle, noise
    frequency=100,    # Hz base frequency
    duration=5.0,     # seconds
    volume=0.3,
    effects={
        "lfo": {"rate": 0.1, "depth": 5},  # Frequency modulation
        "harmonic": 0.5,  # Add harmonic overtones
    }
)
```

### `Client.audio_sequence`
Compose multiple audio events into a sequence.

```python
from kinocut import Client

video = Client()

sequence = [
    {"type": "tone", "freq": 800, "duration": 0.05, "at": 0},
    {"type": "tone", "freq": 1000, "duration": 0.05, "at": 0.1},
    {"type": "preset", "name": "chime-success", "at": 2.0},
    {"type": "whoosh", "direction": "up", "duration": 0.3, "at": 3.0},
]

video.audio_sequence(sequence, output="sound-design.wav")
```

---

## 🔊 **Sound Design Presets**

### `Client.audio_preset`
Pre-configured sound design elements.

```python
from kinocut import Client

video = Client()

# UI interaction sounds
video.audio_preset("ui-blip", pitch="high", output="blip.wav")
video.audio_preset("ui-click", pitch="mid", output="click.wav")
video.audio_preset("ui-whoosh-up", output="whoosh.wav")

# Ambient textures
video.audio_preset("drone-low", output="drone-low.wav")
video.audio_preset("drone-tech", intensity=0.7, output="drone-tech.wav")

# Success/notification
video.audio_preset("chime-success", output="chime.wav")
video.audio_preset("chime-error", output="error.wav")

# Data/processing
video.audio_preset("typing", intensity=0.5, output="typing.wav")
video.audio_preset("scan", duration=1.0, output="scan.wav")
video.audio_preset("data-flow", duration=0.3, output="flow.wav")
```

---

## 🎵 **Audio Composition**

### `Client.audio_compose`
Layer multiple audio tracks with timing.

```python
from kinocut import Client

video = Client()

video.audio_compose(
    tracks=[
        {"file": "drone.wav", "volume": 0.2, "loop": True},
        {"file": "blips.wav", "volume": 0.3, "start": 5.0},
        {"file": "chime.wav", "volume": 0.5, "start": 10.0},
    ],
    duration=15.0,
    output="soundtrack.wav"
)
```

---

## 🎚️ **Audio Effects Chain**

### `Client.audio_effects`
Apply effects to audio.

```python
from kinocut import Client

video = Client()

video.audio_effects(
    input_path="raw.wav",
    output="processed.wav",
    effects=[
        {"type": "lowpass", "freq": 2000},
        {"type": "reverb", "room": 0.3, "damping": 0.5},
        {"type": "compressor", "threshold": -20, "ratio": 4},
        {"type": "normalize", "target": -16},  # LUFS
    ]
)
```

---

## 🎬 **Video + Audio Integration**

### `Client.add_generated_audio`
Add procedurally generated audio to video.

```python
from kinocut import Client

video = Client()

# Generate and add in one call
video.add_generated_audio(
    video="input.mp4",
    audio_config={
        "drone": {"frequency": 100, "volume": 0.2},
        "events": [
            {"type": "blip", "at": 2.0},
            {"type": "chime", "at": 5.0},
        ]
    },
    output="with-audio.mp4"
)
```

---

## 🎹 **MCP Tools Interface**

The same operations are exposed as MCP tools. The public names use the
`audio_*` family, with `video_add_generated_audio` for the video integration:

```json
{
  "name": "audio_synthesize",
  "description": "Generate procedural audio using synthesis",
  "parameters": {
    "waveform": {"type": "string", "enum": ["sine", "square", "sawtooth", "triangle", "noise"]},
    "frequency": {"type": "number", "description": "Base frequency in Hz"},
    "duration": {"type": "number", "description": "Duration in seconds"},
    "volume": {"type": "number", "minimum": 0, "maximum": 1},
    "effects": {"type": "object"}
  }
}
```

```json
{
  "name": "audio_preset",
  "description": "Generate preset sound design elements",
  "parameters": {
    "preset": {"type": "string", "enum": ["ui-blip", "ui-click", "ui-whoosh", "drone-low", "drone-tech", "chime-success", "typing", "scan"]},
    "pitch": {"type": "string", "enum": ["low", "mid", "high"]},
    "direction": {"type": "string", "enum": ["up", "down"]},
    "duration": {"type": "number"},
    "output": {"type": "string"}
  }
}
```

---

## 🔧 **Implementation Notes**

### Tech Stack Options

1. **Python + NumPy** (Pure Python)
   - Generate waveforms as NumPy arrays
   - Write to WAV using `scipy.io.wavfile`
   - Apply effects with `pydub` or custom DSP
   - **Pros:** No external dependencies, fully portable
   - **Cons:** Slower for complex synthesis

2. **Python + Pedalboard** (Spotify)
   - Use `pedalboard` for audio effects
   - `numpy` for synthesis
   - **Pros:** Professional quality effects
   - **Cons:** Heavy dependency

3. **Python + sox** (External)
   - Generate base tones
   - Use `sox` command-line for effects
   - **Pros:** Fast, proven audio tools
   - **Cons:** Requires sox installation

### Recommended: Option 1 (Pure Python)

Most aligned with Kinocut's philosophy of minimal dependencies.

```python
import numpy as np
from scipy.io import wavfile

def generate_tone(freq, duration, sample_rate=44100):
    t = np.linspace(0, duration, int(sample_rate * duration))
    waveform = np.sin(2 * np.pi * freq * t)
    return (waveform * 32767).astype(np.int16)

# Write to file
wavfile.write("tone.wav", 44100, generate_tone(440, 1.0))
```

---

## 📊 **Implemented Surface**

| Feature | Priority | Effort | Value |
|---------|----------|--------|-------|
| `audio_synthesize` | P1 | Medium | High - Core building block |
| `audio_preset` | P1 | Low | High - Easy UX |
| `audio_compose` | P2 | Medium | Medium - Composition layer |
| `audio_effects` | P2 | High | Medium - Polish |
| `video_add_generated_audio` | P1 | Low | High - Integration convenience |

---

## 🎨 **Sound Design Preset Library**

Suggested initial presets:

| Category | Presets |
|----------|---------|
| **UI** | `ui-blip`, `ui-click`, `ui-tap`, `ui-whoosh-up`, `ui-whoosh-down` |
| **Ambient** | `drone-low`, `drone-mid`, `drone-tech`, `drone-ominous` |
| **Notifications** | `chime-success`, `chime-error`, `chime-notification` |
| **Data** | `typing`, `scan`, `processing`, `data-flow`, `upload`, `download` |
| **Nature** | `wind`, `water`, `fire` (abstract, not realistic) |

---

## 🚀 **Original MVP Scope**

The original MVP selected these operations, all of which are now implemented:

1. `audio_synthesize` - Basic waveform generation
2. `audio_preset` - Common sound-design presets
3. `video_add_generated_audio` - Convenience wrapper

The shipped surface has since expanded beyond this original estimate.
