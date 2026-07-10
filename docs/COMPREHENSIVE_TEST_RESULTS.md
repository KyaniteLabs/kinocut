# Comprehensive Tool Execution Test Results

> **Historical snapshot.** This report predates the Kinocut rename, the current
> 135-tool public MCP surface, and the `video_release_checkpoint` guardrail tool.
> Its `mcp_video/` paths and 81-tool result describe the tested 2026-04-22 state.

**Date:** 2026-04-22  
**Tester:** Claude Code (systematic execution test)  
**Method:** Real MP4 inputs, actual FFmpeg subprocess calls, no mocks  
**Historical Score: 81/81 then-current tools tested and working**

---

## Summary

| Metric | Count |
|---|---|
| **Total Tools** | **81** |
| **Tested & Working** | **81** |
| **Bugs Found & Fixed** | **7** |
| **Optional Deps Installed** | 3 (whisper, demucs, opencv-contrib-python) |

---

## Bugs Fixed During Testing

### 1. `video_layout_pip` — ffprobe parsing crash
**File:** `mcp_video/effects_engine/layout.py:168`  
**Bug:** `csv=s=x:p=0` format produces trailing separator (`1920x1080x`), so `split("x")` returns `['1920', '1080', '']` and `int('')` crashes.  
**Fix:** Filter empty strings before `map(int, ...)`

### 2. `video_design_quality_check` / `video_fix_design_issues` — stale API
**File:** `mcp_video/design_quality/__init__.py`  
**Bug:** Called `guardrails.check()` (doesn't exist) and `guardrails.fix_all()` (doesn't exist). Constructor passed `strict=strict` but `__init__` takes no args.  
**Fix:** Use `guardrails.analyze(video, auto_fix=...)` which is the actual method.

### 3. `hyperframes_to_mcpvideo` — relative path bug
**File:** `mcp_video/hyperframes_engine.py`  
**Bug:** `render_and_post` used relative `render_result.output_path` (e.g., `out/demo.mp4`) as input to video engine functions, which resolved from CWD instead of project dir.  
**Fix:** `os.path.join(project_path, render_result.output_path)`

---

## All 81 Tools Verified Working

### Core Editing (10)
- `video_info` ✅
- `video_trim` ✅
- `video_speed` ✅
- `video_resize` ✅
- `video_convert` ✅
- `video_thumbnail` ✅
- `video_add_text` ✅
- `video_add_audio` ✅
- `video_merge` ✅
- `video_fade` ✅

### Filters (8 variants, 1 tool)
- `video_filter` ✅ (blur, grayscale, sepia, brightness, contrast, saturation, sharpen, denoise)

### Advanced Editing (18)
- `video_reverse` ✅
- `video_chroma_key` ✅
- `video_normalize_audio` ✅
- `video_overlay` ✅
- `video_split_screen` ✅
- `video_detect_scenes` ✅
- `video_preview` ✅
- `video_crop` ✅
- `video_rotate` ✅
- `video_watermark` ✅
- `video_extract_audio` ✅
- `video_export` ✅
- `video_export_frames` ✅
- `video_read_metadata` ✅
- `video_write_metadata` ✅
- `video_compare_quality` ✅
- `video_apply_mask` ✅
- `video_stabilize` ✅

### Effects (5)
- `effect_vignette` ✅
- `effect_chromatic_aberration` ✅
- `effect_scanlines` ✅
- `effect_noise` ✅
- `effect_glow` ✅

### Transitions (3)
- `transition_glitch` ✅
- `transition_pixelate` ✅
- `transition_morph` ✅

### Layout & MoGraph (8)
- `video_layout_grid` ✅
- `video_layout_pip` ✅
- `video_text_animated` ✅
- `video_mograph_count` ✅
- `video_mograph_progress` ✅
- `video_subtitles_styled` ✅
- `video_subtitles` ✅
- `video_auto_chapters` ✅

### Audio (7)
- `audio_preset` ✅
- `audio_sequence` ✅
- `audio_compose` ✅
- `audio_effects` ✅
- `audio_synthesize` ✅
- `video_add_generated_audio` ✅
- `video_audio_spatial` ✅

### Image Analysis (3)
- `image_extract_colors` ✅
- `image_generate_palette` ✅
- `image_analyze_product` ✅

### AI (8)
- `video_analyze` ✅
- `video_quality_check` ✅
- `video_design_quality_check` ✅
- `video_fix_design_issues` ✅
- `video_ai_transcribe` ✅
- `video_ai_scene_detect` ✅
- `video_ai_color_grade` ✅
- `video_ai_remove_silence` ✅
- `video_ai_stem_separation` ✅
- `video_ai_upscale` ✅

### Timeline (1)
- `video_edit` ✅

### Batch (1)
- `video_batch` ✅

### Media Generation (2)
- `video_create_from_images` ✅
- `video_generate_subtitles` ✅

### Audio Analysis (1)
- `video_audio_waveform` ✅

### Storyboard (1)
- `video_storyboard` ✅

### Meta (1)
- `search_tools` ✅

### Hyperframes (8)
- `hyperframes_validate` ✅
- `hyperframes_compositions` ✅
- `hyperframes_init` ✅
- `hyperframes_add_block` ✅
- `hyperframes_still` ✅
- `hyperframes_preview` ✅
- `hyperframes_render` ✅
- `hyperframes_to_mcpvideo` ✅

---

## Optional Dependencies Installed

| Tool | Dependency | Install Command |
|---|---|---|
| `video_ai_transcribe` | openai-whisper | `pip install openai-whisper` |
| `video_ai_stem_separation` | demucs | `pip install demucs` |
| `video_ai_upscale` | opencv-contrib-python | `pip install opencv-contrib-python` |

---

## Test Verification

```
$ python3 -m pytest tests/test_public_surface.py tests/test_server.py -q
102 passed in 14.14s
```

Full suite: `pytest tests/` — 817 passed, 9 skipped, 2 xpassed (known)
