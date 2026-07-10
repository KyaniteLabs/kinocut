# 04-hyperframes-video

Create a video from scratch using Hyperframes (HTML-native, Apache 2.0), then post-process with Kinocut.

## Inputs

| Source | File/Location | Description |
|---|---|---|
| Project name | User provided | Name for the new Hyperframes project |
| Template | User provided | `blank`, `warm-grain`, or `swiss-grid` |
| Blocks | User provided | Optional blocks from Hyperframes catalog |
| Post-process | User provided | Kinocut filters, resize, text overlay, etc. |

## Process

1. **01-init**: Use `hyperframes_init` to scaffold a new project
2. **02-blocks**: Use `hyperframes_add_block` to install catalog blocks (optional)
3. **03-validate**: Use `hyperframes_validate` to check project structure
4. **04-render**: Use `hyperframes_render` to generate the base video
5. **05-post-process**: Use Kinocut tools (resize, add_text, watermark, export)

## Outputs

| Artifact | Location | Format |
|---|---|---|
| Hyperframes project | `output/{project_name}/` | HTML/TypeScript project |
| Base render | `output/04_render.mp4` | Raw Hyperframes output |
| Final video | `output/final_video.mp4` | Post-processed MP4 |

## Quality gates

- [ ] Project validates without errors
- [ ] Render completes successfully
- [ ] Post-processed video meets target specs (resolution, duration)
- [ ] Text overlays are readable
- [ ] Audio is present and normalized
