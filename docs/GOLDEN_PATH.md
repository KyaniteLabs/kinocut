# Kinocut golden path

**Goal:** prove Kinocut works on a clean machine with artifacts another agent or human can inspect.

## 60-second success criteria

These three steps must succeed:

| Step | Command | Pass means |
| ---: | --- | --- |
| 1 | `kino doctor` | Required checks OK (FFmpeg + package) |
| 2 | Confidence baseline workflow | Writes final video + quality + checkpoint + receipt |
| 3 | Artifact checks | Fresh receipt, source/final hashes, raw quality >=80, checkpoint media, and pending human review all validate |

One command:

```bash
# from a clone with Python 3.11+ and FFmpeg on PATH
pip install -e .
python scripts/golden_path.py
```

Or with uv / no editable install:

```bash
uv run --no-project --with kinocut python scripts/golden_path.py
```

## What you get

Under `workflows/05-confidence-baseline/output/` (gitignored media):

- `final_clip.mp4` — checked vertical proof clip
- `video_receipt.json` — intent, tools, quality, human-review pending
- `quality.json` — quality gate report
- `release_checkpoint.json` — thumbnail / storyboard / instructions
- intermediate stage files (`01_trimmed.mp4` …)

## Shareable demo pack

```bash
python scripts/generate_golden_pack.py
```

Copies JSON (+ media when present) to `demo/golden-pack/artifacts/` and refreshes
`demo/golden-pack/sample_video_receipt.json` for docs and site demos. See
[demo/golden-pack/README.md](../demo/golden-pack/README.md).

`--skip-run` reuses output only after the same strict run, candidate, quality,
artifact, containment, and hash checks pass. A failed validation or copy leaves
the existing shareable pack unchanged.

## Clean-wheel release acceptance

Release and pull-request CI build a wheel, install it into a clean venv outside
the checkout, and invoke `scripts/verify_onboarding_release.py`. The harness
runs doctor, trim, 9:16 resize, two-cue SRT burn, audio normalization, the raw
quality gate, and `Client.release_checkpoint`. It then requires 1080x1920 MP4
video plus audio, a full decode, exact source/output identities, and four
cue/no-cue frame comparisons.

The deterministic source is synthetic and proves installation and timed visual
change. It does not prove caption readability, transcription accuracy, or
creative quality. A lawful local interview excerpt must pass the same harness;
its receipt stays pending until a person reviews timing, readability, visual
integrity, and audio intelligibility.

## Failure recovery

| Symptom | Fix |
| --- | --- |
| Doctor: FFmpeg missing | `brew install ffmpeg` or `sudo apt install ffmpeg` |
| Doctor: package missing | `pip install kinocut` or `pip install -e .` from clone |
| Workflow import error | Use Python 3.11+; `pip install -e .` |
| Optional AI extras missing | Expected for this path — core golden path does **not** need Whisper/torch |
| Hyperframes errors | Not required for golden path |
| Quality score below 80 or a failed non-advisory check | Inspect `quality.json`; the run is diagnostic evidence, not a green proof |
| Command timeout | Inspect the bounded failure detail; no green/shareable receipt is produced |

## Agent paste prompt

```text
Run the Kinocut golden path from the repo root:
1) kino doctor
2) python scripts/golden_path.py
3) Open workflows/05-confidence-baseline/output/video_receipt.json and summarize tool_calls, quality, and human_review.
Do not publish the clip; human review is still required.
```

## Related

- Public claims (version / tool counts): [public_claims.json](public_claims.json)
- Workflow details: [../workflows/05-confidence-baseline/](../workflows/05-confidence-baseline/)
- Product site: https://kinocut.dev/
