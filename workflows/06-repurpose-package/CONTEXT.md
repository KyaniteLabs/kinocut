# 06-repurpose-package

Turn one source clip into a local platform-ready package with a manifest, variants, thumbnails, storyboards, release checkpoints, and a Video Receipt.

## Inputs

| Source | File/Location | Description |
| --- | --- | --- |
| Source video | Optional CLI argument | If omitted, the workflow generates a tiny synthetic source clip. |
| Platform list | `workflow.py` | Defaults to `youtube-shorts` and `instagram-post` for a fast proof run. |

## Process

1. **01-source**: Generate synthetic source media if no input is supplied.
2. **02-inspect**: Read source duration and resolution with `Client.info`.
3. **03-repurpose**: Use `Client.repurpose` to render platform variants.
4. **04-review**: Collect variant thumbnails, storyboards, and release checkpoints.
5. **05-receipt**: Write `output/video_receipt.json`.

## Outputs

| Artifact | Location | Format |
| --- | --- | --- |
| Source clip | `output/source.mp4` | MP4 |
| Package manifest | `output/package/repurpose_manifest.json` | JSON |
| Platform variants | `output/package/*.mp4` | MP4 |
| Platform review artifacts | `output/package/<platform>/` | Thumbnail, storyboard, checkpoint |
| Video Receipt | `output/video_receipt.json` | JSON |

## Quality Gates

- [ ] Source media is not overwritten.
- [ ] Each variant has an output video.
- [ ] Each variant has thumbnail/storyboard review artifacts.
- [ ] Each variant has a release checkpoint.
- [ ] Human review remains required before publishing.
