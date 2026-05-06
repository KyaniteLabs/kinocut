# mcp-video Testing Documentation

## Overview

mcp-video currently collects **1074 tests** covering public MCP tools, Python client, CLI, FFmpeg operations, AI features, cinematic creation helpers, Hyperframes integration, security hardening, and engine internals. Some tests are environment-sensitive and may skip when optional dependencies or system capabilities are unavailable.

## Test Suite: `tests/test_real_all_features.py`

### Running the Tests

```bash
# Run all tests
python -m pytest tests/test_real_all_features.py -v

# Run specific category
python -m pytest tests/test_real_all_features.py::TestAIFeatures -v
python -m pytest tests/test_real_all_features.py::TestCoreVideoEditing -v

# Skip slow tests (those marked with @pytest.mark.slow)
python -m pytest tests/test_real_all_features.py -v -m "not slow"
```

### Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| **Core Video Editing** | 18 | Trim, merge, resize, speed, rotate, flip, reverse, stabilize, chroma key, blur, watermark, text, overlay, split-screen |
| **Audio Features** | 10 | Extract audio, normalize, synthesize, presets, sequence, compose, effects, add audio, waveform, generated audio |
| **Visual Effects** | 8 | Vignette, chromatic aberration, scanlines, noise, glow, color grade, filters, masks |
| **Transitions** | 3 | Glitch, pixelate, morph |
| **AI Features** | 8 | Scene detection, silence removal, transcription, stem separation, upscale, color grade, spatial audio, color extraction |
| **Layout & Composition** | 8 | Grid layout, PiP, animated text, subtitles, motion graphics (counter, progress), create from images, export frames |
| **Quality & Metadata** | 8 | Quality check, design quality, fix design issues, compare quality, auto chapters, detailed info, read/write metadata |
| **Utility** | 7 | Convert format, preview, storyboard, thumbnail, batch process, timeline edit, generate subtitles |
| **Total** | **70** | **100% passing** |

## Hyperframes Tests

Run Hyperframes-specific tests (requires Node.js 22+ and `npx hyperframes`):

```bash
python -m pytest tests/test_hyperframes_engine.py -v
python -m pytest tests/test_hyperframes_engine.py -v -m hyperframes
```

Run without Hyperframes integration tests:

```bash
python -m pytest tests/ -v -m "not hyperframes"
```

## AI Features Tested

### 1. AI Scene Detection (`test_40_ai_scene_detect`)
- Detects scene changes in video
- Returns list of timestamps
- Threshold configurable

### 2. AI Silence Removal (`test_41_ai_remove_silence`)
- Automatically removes silent portions
- Configurable threshold and minimum duration

### 3. AI Transcription (`test_42_ai_transcribe`)
- Uses OpenAI Whisper
- Tiny model for tests (fast)
- Exports SRT subtitles

### 4. AI Stem Separation (`test_43_ai_stem_separation`)
- Uses Facebook Demucs
- Separates vocals, drums, bass, other
- Provided by the `mcp-video[ai]` extra (`demucs`, `torch`, `torchaudio`)

### 5. AI Upscale (`test_44_ai_upscale`)
- OpenCV DNN with FSRCNN model (57KB, fast)
- Real-ESRGAN fallback (if basicsr fixed)
- 2x and 4x upscaling
- Provided by the `mcp-video[ai]` extra (`opencv-contrib-python`, `numpy`)

### 6. AI Color Grade (`test_45_ai_color_grade`)
- Auto color grading
- Cinematic presets

### 7. Spatial Audio (`test_46_audio_spatial`)
- 3D audio positioning
- HRTF-based spatialization

### 8. Color Extraction (`test_47_extract_colors`)
- Extract dominant colors from frames
- K-means clustering

## System Dependencies Verified

### FFmpeg with vidstab
```bash
# macOS
brew install ffmpeg-full  # Includes vidstabdetect/vidstabtransform

# Verify
ffmpeg -filters | grep vidstab
```

### Python Packages
```bash
# Install the optional AI stack
pip install "mcp-video[ai]"

# Or install individual packages if you only need a subset
pip install demucs torch torchaudio openai-whisper realesrgan basicsr imagehash numpy opencv-contrib-python
```

## Test Fixtures

### Sample Clips
- Generated via FFmpeg lavfi (2-second color bars)
- Colors: red, blue, green, yellow
- 640x480 @ 30fps with audio

### Short Test Clip
- 3-second clip for quality checks
- Prevents timeout on full-length video

### Test Videos
- `out/McpVideoExplainer-FINAL.mp4` (100s explainer video)
- Used for tests that require longer content

## Performance Notes

| Test | Duration | Notes |
|------|----------|-------|
| test_12_stabilize_video | ~60s | Uses 2s clip (full video too slow) |
| test_44_ai_upscale | ~30s | FSRCNN model (fast CPU inference) |
| test_43_ai_stem_separation | ~30s | Downloads model on first run |
| Full suite | ~5min | All 70 real-media tests |
| Full project suite | Environment-dependent | 1074 tests collected |

## Recent Fixes

### Test Stability Improvements
1. **test_12_stabilize_video** - Changed to use 2s clip instead of 100s video
2. **test_56-59** (quality checks) - Use 3s short_test_clip fixture
3. **test_44_ai_upscale** - Implemented OpenCV DNN fallback (Real-ESRGAN basicsr bug)

### Bug Fixes
1. **ProcessingError signature** - Fixed `compare_quality()` to use correct parameters
2. **Quality check assertions** - Handle both dict and object return types
3. **Resolution mismatch** - Auto-scale videos for comparison

## CI/CD

The test suite is designed for CI:
- Tests skip gracefully if optional dependencies missing
- Tests skip if FFmpeg filters unavailable (vidstab)
- Real media tests validate actual functionality

## Adding New Tests

When adding features:
1. Add test to appropriate class in `test_real_all_features.py`
2. Use `sample_clips` or `short_test_clip` fixtures for speed
3. Mark slow tests with `@pytest.mark.slow`
4. Skip conditionally if dependencies optional:

```python
@pytest.mark.skipif(
    not importlib.util.find_spec("optional_package"),
    reason="Optional package not installed"
)
def test_new_feature(self, client, sample_clips):
    ...
```

## Adversarial & Security Tests

Security-focused tests in `tests/test_adversarial_audit.py` verify:
- FFmpeg filter injection prevention
- Null byte rejection on all input paths
- Color/format validation hardening
- Parameter boundary enforcement

## Test Coverage

Every MCP tool has a corresponding test:
- Public MCP, client, CLI, and real-media workflows are covered across the test suite
- Real FFmpeg operations validated
- Error handling verified
- Edge cases covered (silent videos, different codecs, etc.)
- Remotion integration completely removed (PR #163)
