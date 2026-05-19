# Factory intake for issue #302: effect_noise with mode='film' produces extreme green/magenta chromatic distortion on image-based videos

Repository: `KyaniteLabs/mcp-video`
Category: `llm_fix`
Source issue: `#302`

## User request

# Bug Report: `effect_noise` Produces Extreme Green/Magenta Chromatic Distortion

**Repository:** KyaniteLabs/mcp-video  
**Version:** 1.4.0  
**Labels:** bug, effects

---

## Bug Summary

The `effect_noise` tool with `mode="film"` and `animated=true` applies extreme green/magenta chromatic aberration that completely destroys video content, rather than subtle film grain.

## Reproduction Steps

1. Create a video from a static image using `video_create_from_images`
2. Apply `effect_noise` with these params:
   - `intensity: 0.04`
   - `mode: "film"`
   - `animated: true`
3. Output shows psychedelic green/purple color channels, not film grain

## Expected Behavior

Subtle, natural-looking film grain texture overlaid on the video — monochrome noise that slightly varies per frame.

## Actual Behavior

The entire frame is flooded with green and magenta color separation. The effect looks like extreme chromatic aberration or a broken RGB channel offset. Text overlays become unreadable. The distortion is so severe it makes the footage unusable.

### Before effect_noise (clean frame):
- Dark cinematic image with warm tones
- White text overlay clearly readable

### After effect_noise (destroyed frame):
- Entire frame dominated by neon green and purple
- Text completely lost in the color noise
- Looks like a broken VHS tape or corrupted video file

## Environment

| Key | Value |
|-----|-------|
| mcp-video | 1.4.0 |
| FFmpeg | 8.1 |
| OS | macOS |
| Input | 1280×720 MP4 created from JPEG via `video_create_from_images` |

## Additional Context

The raw images themselves were fine — the bug is specifically in how `effect_noise` processes the video. When I rebuilt the same pipeline *without* the `effect_noise` step, the output was clean and professional. This suggests the FFmpeg filter chain in the noise effect has a color space or chroma subsampling issue when applied to image-to-video sources.

## Workaround

Skip `effect_noise` entirely for image-based videos. The images already have enough texture.

## Suggested Fix

Investigate the FFmpeg filtergraph in `effect_noise`. The `noise` filter with `c0,c1,c2` may be applying independent per-channel noise with `allp` point filter, which can cause channel misalignment. Consider:

1. Using `c0` (luma only) for film grain instead of all planes
2. Adding `format=yuv420p` before noise to ensure consistent chroma subsampling
3. Using `geq` for monochrome noise across all channels equally

## Factory interpretation

This issue was picked up by `issue-closer`, but no safe code edit was
produced by the configured agent providers. The Factory is therefore
converting the issue into an implementation contract instead of silently
skipping it.

## Acceptance contract

- Confirm the desired behavior from the issue title and body.
- Identify the smallest implementation slice that can ship independently.
- Add or update tests/proofs for that slice before merging implementation.
- Keep credentials, local machine paths, and deployment secrets out of the repo.
- Close or update the source issue when the implementation PR lands.

## Next Factory action

Dispatch a repo worker against this contract. If the request is too broad,
split it into smaller `agent-ready` issues with concrete acceptance checks.
