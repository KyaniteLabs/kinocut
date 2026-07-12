# Kinocut Testing Documentation

## Overview

Kinocut uses focused tests for public MCP tools, the Python client, CLI behavior, FFmpeg operations, AI features, cinematic creation helpers, Hyperframes integration, repurposing packages, security hardening, and engine internals. Some tests are environment-sensitive and may skip when optional dependencies or system capabilities are unavailable.

## Required repository gate

Every implementation change must pass the complete suite on the exact integrated commit:

```bash
python3 -m pytest tests/ -x -q --tb=short
python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"
```

A focused pass is development evidence only. A full-suite result from an older commit is not
current completion proof.

## AI-video contract and media families

The contract-first program adds focused coverage for:

- canonical record IDs, strict schemas, migrations, append-only supersession, lock/atomicity,
  path privacy, symlink/hard-link defenses, and content-addressed ingest;
- loss-proof audio duration behavior, authored ASS preservation, dimension-aware subtitle burn,
  and ASR EOF clamping;
- unified preflight, full-decode integrity, deterministic sampled artifacts, motion strips,
  declared-region crops, temporal defect intervals, and bounded optional providers;
- exact-human-evidence verdicts, acceptance evaluation, protected-element collisions,
  complete audio preservation, source snapshot identity, salvage lineage, and public surface parity.

Run the focused families while developing, then run the repository gate:

```bash
python3 -m pytest tests/test_contracts_*.py tests/test_projectstore_*.py -q --tb=short
python3 -m pytest tests/test_aivideo_*.py tests/test_body_swap.py tests/test_wave3_surfaces.py -q --tb=short
python3 -m pytest tests/test_public_surface.py -q --tb=short
```

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

### Coverage Areas

| Category | Description |
|----------|-------------|
| **Core Video Editing** | Trim, merge, resize, speed, rotate, flip, reverse, stabilize, chroma key, blur, watermark, text, overlay, split-screen |
| **Audio Features** | Extract audio, normalize, synthesize, presets, sequence, compose, effects, add audio, waveform, generated audio |
| **Visual Effects** | Vignette, chromatic aberration, scanlines, noise, glow, color grade, filters, masks |
| **Transitions** | Glitch, pixelate, morph |
| **AI Features** | Scene detection, silence removal, transcription, stem separation, upscale, color grade, spatial audio, color extraction |
| **Planning and Creation** | PUSHING CREATION project scaffolds, style packs, storyboard parsing, shot prompt rendering |
| **Hyperframes** | Project scaffolds, render/snapshot/still flows, layout inspection, catalog, capture, local TTS, transcription, background removal, diagnostics, benchmarks |
| **Repurposing** | Dry-run manifests, platform variants, thumbnails, storyboards, release-checkpoint artifacts |
| **Layout & Composition** | Grid layout, PiP, animated text, subtitles, motion graphics, create from images, export frames |
| **Quality & Metadata** | Quality check, design quality, fix design issues, compare quality, auto chapters, detailed info, read/write metadata |
| **Utility** | Convert format, preview, storyboard, thumbnail, batch process, timeline edit, generate subtitles |

## Hyperframes Tests

Run Hyperframes-specific tests (requires Node.js 22+ and a resolvable local Hyperframes CLI):

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
- Provided by the `kinocut[ai]` extra (`demucs`, `torch`, `torchaudio`, `torchcodec`)

### 5. AI Upscale (`test_44_ai_upscale`)
- OpenCV DNN with FSRCNN model (57KB, fast)
- Real-ESRGAN path only where BasicSR can build; Python 3.13 uses the OpenCV fallback
- 2x and 4x upscaling
- Provided by the `kinocut[ai]` extra (`opencv-contrib-python`, `numpy`)

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
pip install "kinocut[ai]"

# Or install individual packages if you only need a subset
pip install demucs torch torchaudio torchcodec openai-whisper imagehash numpy opencv-contrib-python
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
| Real-media feature sweep | ~5min | Exercises media-producing paths |
| Full project suite | Environment-dependent | Exercises unit, integration, public-surface, and security coverage |

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
- Remotion integration completely removed in v1.3.1 (PR #163)
