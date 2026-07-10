# Kinocut Features Roadmap

Consolidated feature backlog from explainer video project.

**Status Update: 2026-03-29** - v1.0 released with real-media coverage for the core feature set.

## Verification

Core media features are tested with real media files. Run `python -m pytest tests/test_real_all_features.py -v` to verify.

| Category | Status |
|----------|--------|
| Core Video Editing | Covered |
| Audio Features | Covered |
| Visual Effects | Covered |
| Transitions | Covered |
| AI Features | Covered |
| Layout & Composition | Covered |
| Quality & Metadata | Covered |
| Utility | Covered |

### AI Feature Implementation Details

- **Stem Separation**: Uses Demucs (Facebook Research) with torchcodec
- **AI Upscale**: OpenCV DNN (FSRCNN) with Real-ESRGAN fallback
- **Transcription**: OpenAI Whisper (tiny model for tests)
- **Stabilization**: FFmpeg vidstabdetect/vidstabtransform (requires ffmpeg-full)

### System Dependencies

Fully tested and working:
- ✅ FFmpeg with vidstab support (via `brew install ffmpeg-full`)
- ✅ demucs + torchcodec for stem separation
- ✅ opencv-contrib-python for AI upscaling
- ✅ whisper for transcription

## v1.0 Release Features (Completed 2026-03-28)

### AI-Powered Features
- ✅ `video_ai_remove_silence` - Auto-remove silent sections (v1.0)
- ✅ `video_ai_transcribe` - Speech-to-text with Whisper (v1.0)
- ✅ `video_ai_scene_detect` - ML scene detection (v1.0)
- ✅ `video_ai_stem_separation` - Audio stem separation (v1.0)
- ✅ `video_ai_upscale` - AI super-resolution (v1.0)
- ✅ `video_ai_color_grade` - Auto color grading (v1.0)
- ✅ `video_audio_spatial` - 3D spatial audio (v1.0)

### Audio Synthesis (Shipped v0.9.0)
- ✅ `audio_preset` - 18+ pre-configured sounds
- ✅ `audio_synthesize` - Procedural waveform generation
- ✅ `audio_sequence` - Timed sequence composition
- ✅ `audio_compose` - Multi-track mixing
- ✅ `audio_effects` - Effects chain processing
- ✅ `video_add_generated_audio` - One-shot video+audio

### Visual Effects (Shipped v0.9.0)
- ✅ `video_effect_vignette` - Darkened edges
- ✅ `video_effect_chromatic_aberration` - RGB separation
- ✅ `video_effect_scanlines` - CRT scanlines
- ✅ `video_effect_noise` - Film/digital noise
- ✅ `video_effect_glow` - Bloom/glow effect

### Video Transitions (Shipped v1.0)
- ✅ `video_transition_glitch` - Glitch effect transition
- ✅ `video_transition_pixelate` - Pixel dissolve transition
- ✅ `video_transition_morph` - Mesh warp transition

### Layout & Composition (Shipped v0.9.0)
- ✅ `video_layout_grid` - Grid-based multi-video layout
- ✅ `video_layout_pip` - Picture-in-picture overlay

### Text & Typography (Shipped v0.9.0)
- ✅ `video_text_animated` - Animated text with presets
- ✅ `video_subtitles_styled` - Burn subtitles with custom styling

### Motion Graphics (Shipped v0.9.0)
- ✅ `video_mograph_count` - Animated number counter
- ✅ `video_mograph_progress` - Progress bar/loading animation

### Utility (Shipped v0.9.0)
- ✅ `video_info_detailed` - Extended video metadata
- ✅ `video_auto_chapters` - Auto-detect scene changes

---

## 🎵 **Audio Synthesis & Sound Design**

### `Client.audio_synthesize`
Generate audio procedurally using synthesis.

```python
from kinocut import Client

video = Client()

video.audio_synthesize(
    output="drone.wav",
    waveform="sine",      # sine, square, sawtooth, triangle, noise
    frequency=100,        # Hz base frequency
    duration=5.0,         # seconds
    volume=0.3,
    effects={
        "envelope": {"attack": 0.1, "decay": 0.2, "sustain": 0.7, "release": 0.5},
    }
)
```

### `Client.audio_preset`
Pre-configured sound design elements.

```python
from kinocut import Client

video = Client()

# UI interaction
video.audio_preset("ui-blip", pitch="high", output="blip.wav")
video.audio_preset("ui-click", pitch="mid", output="click.wav")
video.audio_preset("ui-whoosh-up", duration=0.3, output="whoosh.wav")

# Ambient textures
video.audio_preset("drone-low", output="drone.wav")
video.audio_preset("drone-tech", intensity=0.7, output="drone-tech.wav")

# Notifications
video.audio_preset("chime-success", output="success.wav")
video.audio_preset("chime-error", output="error.wav")

# Data/Processing
video.audio_preset("typing", intensity=0.5, output="typing.wav")
video.audio_preset("scan", duration=1.0, output="scan.wav")
video.audio_preset("data-flow", duration=0.3, output="flow.wav")
```

**Available presets:**
- UI: `ui-blip`, `ui-click`, `ui-tap`, `ui-whoosh-up`, `ui-whoosh-down`
- Ambient: `drone-low`, `drone-mid`, `drone-tech`, `drone-ominous`
- Notifications: `chime-success`, `chime-error`, `chime-notification`
- Data: `typing`, `scan`, `processing`, `data-flow`, `upload`, `download`

### `Client.audio_sequence`
Compose multiple audio events into a timed sequence.

```python
from kinocut import Client

video = Client()

sequence = [
    {"type": "tone", "freq": 800, "duration": 0.05, "at": 0},
    {"type": "tone", "freq": 1000, "duration": 0.05, "at": 0.1},
    {"type": "preset", "name": "chime-success", "at": 2.0},
    {"type": "whoosh", "direction": "up", "duration": 0.3, "at": 3.0},
    {"type": "preset", "name": "typing", "at": 5.0, "duration": 2.0},
]

video.audio_sequence(sequence, output="soundtrack.wav")
```

### `Client.audio_compose`
Layer multiple audio tracks with mixing.

```python
from kinocut import Client

video = Client()

video.audio_compose(
    tracks=[
        {"file": "drone.wav", "volume": 0.2, "loop": True, "start": 0},
        {"file": "blips.wav", "volume": 0.3, "start": 5.0},
        {"file": "chime.wav", "volume": 0.5, "start": 10.0},
    ],
    duration=15.0,
    output="final-audio.wav"
)
```

### `Client.audio_effects`
Apply audio effects chain.

```python
from kinocut import Client

video = Client()

video.audio_effects(
    input_path="raw.wav",
    output="processed.wav",
    effects=[
        {"type": "lowpass", "frequency": 2000},
        {"type": "highpass", "frequency": 80},
        {"type": "reverb", "room_size": 0.3, "damping": 0.5, "wet_level": 0.2},
        {"type": "compressor", "threshold": -20, "ratio": 4, "attack": 0.01, "release": 0.1},
        {"type": "normalize", "target_lufs": -16},  # YouTube standard
    ]
)
```

### `Client.add_generated_audio`
One-shot video + generated audio.

```python
from kinocut import Client

video = Client()

video.add_generated_audio(
    video="input.mp4",
    audio_config={
        "drone": {"frequency": 100, "volume": 0.2},
        "events": [
            {"type": "preset", "name": "ui-blip", "at": 2.0},
            {"type": "preset", "name": "chime-success", "at": 5.0},
            {"type": "whoosh", "at": 10.0},
        ]
    },
    output="with-audio.mp4"
)
```

---

## 🎨 **Visual Effects & Filters**

### `video_effect_chromatic_aberration`
RGB channel separation effect.

```python
video_effect_chromatic_aberration(
    "input.mp4",
    output="output.mp4",
    intensity=2.0,      # pixel offset
    angle=0,            # separation direction in degrees
)
```

### `video_effect_vignette`
Darkened edges with adjustable curve.

```python
video_effect_vignette(
    "input.mp4",
    output="output.mp4",
    intensity=0.5,      # 0-1 darkness
    radius=0.8,         # vignette radius (0-1)
    smoothness=0.5,     # edge softness
)
```

### `video_effect_scanlines`
CRT-style scanline overlay.

```python
video_effect_scanlines(
    "input.mp4",
    output="output.mp4",
    line_height=2,      # pixels per line
    opacity=0.3,        # line opacity
    flicker=0.1,        # subtle brightness variation
)
```

### `video_effect_noise`
Film grain / digital noise.

```python
video_effect_noise(
    "input.mp4",
    output="output.mp4",
    intensity=0.05,     # noise amount
    mode="film",        # "film", "digital", "color"
    animated=True,      # static or changing per frame
)
```

### `video_effect_glow`
Bloom/glow effect for highlights.

```python
video_effect_glow(
    "input.mp4",
    output="output.mp4",
    intensity=0.5,      # glow strength
    radius=10,          # blur radius
    threshold=0.7,      # brightness threshold for glow
)
```

---

## 📝 **Text & Typography**

### `video_text_animated`
Animated text with presets.

```python
video_text_animated(
    "input.mp4",
    text="Hello World",
    output="output.mp4",
    animation="typewriter",  # "fade", "slide-up", "typewriter", "glitch"
    font="JetBrains-Mono",
    size=48,
    color="#CCFF00",
    position="center",
    start=1.0,              # seconds
    duration=3.0,
)
```

### `video_subtitles_styled`
Burn subtitles from SRT/VTT with styling.

```python
video_subtitles_styled(
    "video.mp4",
    subtitles="captions.srt",
    output="output.mp4",
    style={
        "font": "Inter",
        "size": 32,
        "color": "#FFFFFF",
        "outline": 2,
        "outline_color": "#000000",
        "background": "rgba(0,0,0,0.5)",
        "position": "bottom",
    }
)
```

---

## 🎬 **Transitions**

### `video_transition_glitch`
Glitch/distortion transition.

```python
video_transition_glitch(
    "clip1.mp4",
    "clip2.mp4",
    output="output.mp4",
    duration=0.5,
    intensity=0.3,
)
```

### `video_transition_pixelate`
Pixel dissolve transition.

```python
video_transition_pixelate(
    "clip1.mp4",
    "clip2.mp4",
    output="output.mp4",
    duration=0.4,
    pixel_size=50,      # max pixel size during transition
)
```

### `video_transition_morph`
Mesh warp morph transition.

```python
video_transition_morph(
    "clip1.mp4",
    "clip2.mp4",
    output="output.mp4",
    duration=0.6,
    mesh_size=10,       # grid subdivisions
)
```

---

## 📐 **Layout & Composition**

### `video_layout_grid`
Grid-based multi-video layout.

```python
video_layout_grid(
    clips=["a.mp4", "b.mp4", "c.mp4", "d.mp4"],
    layout="2x2",           # "2x2", "3x1", "1x3", "2x3"
    output="grid.mp4",
    gap=10,                 # pixels between clips
    padding=20,
    background="#141414",
)
```

### `video_layout_pip`
Picture-in-picture overlay.

```python
video_layout_pip(
    main="main.mp4",
    pip="pip.mp4",
    output="output.mp4",
    position="bottom-right",  # "top-left", "top-right", "bottom-left", "bottom-right"
    size=0.25,                # 25% of main video
    margin=20,
    rounded_corners=True,
    border=True,
    border_color="#CCFF00",
    border_width=2,
)
```

---

## 🎮 **Motion Graphics**

### `video_mograph_count`
Animated number counter.

```python
video_mograph_count(
    start=0,
    end=43,
    duration=2.0,
    output="counter.mp4",
    style={
        "font": "Inter-Black",
        "size": 160,
        "color": "gradient",  # uses theme gradient
        "glow": True,
    }
)
```

### `video_mograph_progress`
Progress bar / loading animation.

```python
video_mograph_progress(
    duration=3.0,
    output="progress.mp4",
    style="bar",            # "bar", "circle", "dots"
    color="#CCFF00",
    track_color="#333333",
)
```

---

## 🔧 **Utility & Helpers**

### `video_info_detailed`
Extended video metadata.

```python
info = video_info_detailed("video.mp4")
# Returns:
# {
#   "duration": 70.0,
#   "fps": 30,
#   "resolution": [1920, 1080],
#   "bitrate": 5000000,
#   "has_audio": False,
#   "scene_changes": [2.5, 5.1, 8.3],  # auto-detected cuts
#   "dominant_colors": ["#141414", "#CCFF00", "#7C3AED"],
# }
```

### `video_auto_chapters`
Auto-detect scene changes and create chapters.

```python
chapters = video_auto_chapters("video.mp4", threshold=0.3)
# Returns list of (timestamp, description) tuples
```

---

## 📊 **Priority Matrix**

| Feature | Priority | Effort | Impact | Status | Notes |
|---------|----------|--------|--------|--------|-------|
| `video_audio_preset` | P1 | Low | High | ✅ Complete | Most common use case |
| `video_audio_synthesize` | P1 | Medium | High | ✅ Complete | Core building block |
| `video_effect_vignette` | P1 | Low | Medium | ✅ Complete | Simple, popular |
| `video_effect_chromatic_aberration` | P2 | Low | Medium | ✅ Complete | Trendy effect |
| `video_text_animated` | P1 | Medium | High | ✅ Complete | High user demand |
| `video_layout_pip` | P2 | Low | Medium | ✅ Complete | Common need |
| `video_effect_glow` | P2 | Medium | Medium | ✅ Complete | Good for tech vids |
| `video_add_generated_audio` | P1 | Low | High | ✅ Complete | Convenience wrapper |
| `video_mograph_count` | P2 | Medium | Medium | ✅ Complete | Specific use case |
| `video_auto_chapters` | P3 | Medium | Low | ✅ Complete | Nice to have |
| `video_ai_remove_silence` | P1 | Medium | High | ✅ Complete | v1.0 feature |
| `video_ai_transcribe` | P1 | Medium | High | ✅ Complete | v1.0 feature |
| `video_ai_scene_detect` | P1 | Medium | High | ✅ Complete | v1.0 feature |
| `video_ai_stem_separation` | P1 | High | High | ✅ Complete | v1.0 feature |
| `video_ai_upscale` | P1 | High | High | ✅ Complete | v1.0 feature |
| `video_ai_color_grade` | P2 | Medium | Medium | ✅ Complete | v1.0 feature |
| `video_audio_spatial` | P2 | Medium | Medium | ✅ Complete | v1.0 feature |
| `video_transition_glitch` | P2 | Medium | Medium | ✅ Complete | v1.0 feature |
| `video_transition_pixelate` | P2 | Low | Medium | ✅ Complete | v1.0 feature |
| `video_transition_morph` | P3 | High | Medium | ✅ Complete | v1.0 feature |

---

## 🔬 **Research / Future**

### v1.1+ Ideas
- `video_ai_object_tracking` - Track objects across frames
- `video_ai_style_transfer` - Artistic style transfer
- `video_ai_lip_sync` - Auto-sync audio to lip movement
- `video_360_stabilization` - Stabilize 360° footage
- `video_hdr_conversion` - SDR to HDR conversion

---

## 💻 **Implementation Notes**

### Audio Synthesis Tech Stack

**Option 1: Pure NumPy** (Recommended)
```python
import numpy as np
from scipy.io import wavfile

def generate_sine(freq, duration, sr=44100):
    t = np.linspace(0, duration, int(sr * duration))
    return np.sin(2 * np.pi * freq * t)
```
- Zero external dependencies
- Fully portable
- Fast enough for short clips

**Option 2: Pedalboard (Spotify)**
```python
from pedalboard import Reverb, Compressor
```
- Professional effects quality
- Heavy dependency

### Video Effects Stack

Most effects can be implemented with:
- FFmpeg filters (`chromashift`, `vignette`, etc.)
- Or Python + OpenCV for custom effects
- Or PIL/Pillow for simple frame processing

### Text Rendering

- PIL/Pillow for simple text
- Pango/Cairo for advanced typography
- Or use ImageMagick via subprocess

---

## 📝 **MCP Tools Schema**

Each shipped feature is exposed as an MCP tool:

```json
{
  "name": "audio_preset",
  "description": "Generate preset sound design element",
  "inputSchema": {
    "type": "object",
    "properties": {
      "preset": {"type": "string", "enum": ["ui-blip", "ui-click", "chime-success", "drone-low", "typing", "scan"]},
      "pitch": {"type": "string", "enum": ["low", "mid", "high"]},
      "duration": {"type": "number"},
      "output_path": {"type": "string"}
    },
    "required": ["preset"]
  }
}
```

---

*Last updated: 2026-03-28*
*Status: v1.0 Released - All planned features complete*
