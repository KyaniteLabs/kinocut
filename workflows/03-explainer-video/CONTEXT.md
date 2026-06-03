# 03-explainer-video

Build a branded explainer video from scratch using synthesized audio, scenes, effects, and transitions.

## Inputs

| Source | File/Location | Description |
|---|---|---|
| Script | User provided | 90-120 second script with scene breakdown |
| Brand colors | references/brand_guide.md | Primary/secondary colors, fonts |
| Audio presets | references/audio_presets.md | Which procedural audio to use per scene |

## Process

1. **01-audio**: Use `audio_preset` and `audio_compose` to generate soundtrack
2. **02-scenes**: Create base scene videos with solid colors and text overlays
3. **03-effects**: Apply `effect_vignette`, `effect_glow`, `effect_chromatic_aberration` per scene
4. **04-transitions**: Use `transition_glitch`, `transition_pixelate`, `transition_morph` between scenes
5. **05-assemble**: Use `video_merge` to combine scenes with transitions
6. **06-audio-mix**: Use `video_add_audio` to layer soundtrack
7. **07-export**: Use `video_convert` for final format
8. **08-quality-checkpoint**: Run quality check and release checkpoint
9. **09-receipt**: Write `output/video_receipt.json`

## Outputs

| Artifact | Location | Format |
|---|---|---|
| Soundtrack | output/01_soundtrack.wav | Mixed procedural audio |
| Scene clips | output/02_scene_*.mp4 | Individual scene videos |
| Effect clips | output/03_scene_*_fx.mp4 | Scenes with effects applied |
| Transition clips | output/04_transition_*.mp4 | Scene-to-scene transitions |
| Assembled video | output/05_assembled.mp4 | Merged scenes |
| Final video | output/final_video.mp4 | MP4 with audio mix |
| Quality report | output/quality.json | JSON |
| Release checkpoint | output/checkpoint/ | JSON + thumbnail/storyboard |
| Video Receipt | output/video_receipt.json | JSON |

## Quality gates

- [ ] Total duration matches script (90-120s)
- [ ] All transitions are smooth (no audio pops)
- [ ] Brand colors used consistently
- [ ] Text is readable at 1080p
- [ ] Audio levels are consistent across scenes
- [ ] Release checkpoint creates thumbnail and storyboard artifacts
- [ ] Video Receipt keeps human review pending before publishing
