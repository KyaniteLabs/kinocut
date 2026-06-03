# Fresh Install Confidence Baseline - 2026-06-03

## BLUF

Published `mcp-video` can install, diagnose, edit, and checkpoint a tiny generated video from a clean temp directory.

The proof also surfaced a useful trust gap: an ad hoc edit path produced a quiet-audio warning, while the staged `01-social-media-clip` workflow normalized audio and passed quality checks. That supports the product thesis that trusted workflows should produce receipts, not just output files.

## Environment

| Item | Result |
| --- | --- |
| Proof directory | `/tmp/mcp-video-confidence-proof-2026-06-03` |
| Install path | `uvx --from mcp-video` |
| Package version | `mcp-video 1.4.1` |
| FFmpeg | `ffmpeg 8.1` |
| ffprobe | `ffprobe 8.1` |
| Python in uv env | `Python 3.12.12` |
| Hyperframes CLI | `0.6.69` |

Doctor summary:

```text
required_ok=true
missing_required=[]
total_checks=34
passed=12
optional_available=6
```

Optional dependency notes:

- Image, transcription, stem-separation, upscale, enhanced audio, and CRUSH shader extras were not installed in the fresh minimal run.
- `@hyperframes/core` was not available to Node's package resolver, even though the Hyperframes CLI was available.

## Proof Commands

```bash
mkdir -p /tmp/mcp-video-confidence-proof-2026-06-03
cd /tmp/mcp-video-confidence-proof-2026-06-03

ffmpeg -y \
  -f lavfi -i testsrc2=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 6 \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac \
  source.mp4

uvx --from mcp-video mcp-video doctor --json > doctor.json
uvx --from mcp-video mcp-video trim source.mp4 -s 00:00:01 -d 00:00:04 -o outputs/trimmed.mp4
uvx --from mcp-video mcp-video add-text outputs/trimmed.mp4 "MCP video proof" -p top-center --size 48 --duration 4 -o outputs/captioned.mp4
uvx --from mcp-video mcp-video resize outputs/captioned.mp4 -a 9:16 -q high -o outputs/vertical.mp4
uvx --from mcp-video mcp-video video-quality-check outputs/vertical.mp4 --format json > outputs/quality.json
uvx --from mcp-video mcp-video storyboard outputs/vertical.mp4 -o outputs/storyboard -n 4
```

Release checkpoint was created through the Python client:

```python
from mcp_video import Client

client = Client()
client.release_checkpoint(
    "outputs/vertical.mp4",
    output_dir="checkpoint",
    min_score=50,
    frame_count=4,
)
```

## Ad Hoc Path Result

Generated artifact:

```text
outputs/vertical.mp4
```

ffprobe result:

```text
codec=h264
width=1080
height=1920
duration=4.000000
```

Quality result:

```text
overall_score=68.9
all_passed=false
recommendation=Audio is too quiet (-21.8 LUFS). Target: -16 LUFS
```

Release checkpoint result:

```text
review_required=true
thumbnail=checkpoint/thumbnail.jpg
storyboard_frames=4
instructions=Open the thumbnail/storyboard and inspect the final video before publishing.
```

Interpretation:

- The edit chain works.
- The release checkpoint creates review artifacts.
- Quiet audio stays visible in the quality report.
- A Video Receipt should preserve this warning so the user does not mistake "rendered" for "ready."

## Staged Workflow Result

Command:

```bash
uv run --no-project --with mcp-video \
  python workflows/01-social-media-clip/workflow.py \
  /tmp/mcp-video-confidence-proof-2026-06-03/source.mp4
```

The workflow completed these stages:

1. Trimmed source video.
2. Resized to 9:16 vertical format.
3. Added hook text.
4. Normalized audio to `-14 LUFS`.
5. Exported final MP4.

Quality check on `workflows/01-social-media-clip/output/final_clip.mp4`:

```text
overall_score=70.3
all_passed=true
audio_loudness=-14.03 LUFS
recommendations=[]
```

Interpretation:

- The staged workflow fixes the quiet-audio issue found in the ad hoc path.
- This supports making workflows and receipts the primary confidence surface.

## Local Project Resolver Note

Running `uv run --with mcp-video ...` from inside the repo attempted to resolve the local project and failed because `mcp-video[audio-all]` depends on `meltysynth>=1.0`, which was not found in the package registry for the resolver split.

Workaround for published-package proof:

```bash
uv run --no-project --with mcp-video python workflows/01-social-media-clip/workflow.py /path/to/source.mp4
```

Follow-up:

- Decide whether the local project metadata should avoid an unsatisfiable `audio-all` extra or constrain supported Python versions/extras so developer onboarding is less surprising.

## Confidence Verdict

This baseline increases confidence in mcp-video as a product wedge because it proves:

1. Published install and CLI discovery work.
2. Required dependencies are detected.
3. A real generated video can be edited to vertical output.
4. Quality checks catch a real issue.
5. The staged workflow resolves that issue.
6. Release checkpoint creates review artifacts and keeps human review in the loop.

