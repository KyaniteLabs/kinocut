# Stream to Shorts

Kinocut’s `shorts` workflow turns a completed long-form recording into reviewable clip candidates and, after explicit human approval, vertical YouTube Shorts and Instagram Reels packages. It never posts publicly.

## Capability matrix

| Capability | Status | Current behavior |
|---|---|---|
| Intake and source preservation | Present | Probes before processing; records duration, resolution, audio, format, and SHA-256; rejects missing video/audio with recovery guidance; never modifies the source. |
| 30–60 minute transcription | Present with optional dependency | Local Whisper works through `kinocut[transcribe]`; callers may provide transcript segments from an operator-configured provider. Long-form chunk planning/merge supports recordings up to Kinocut’s four-hour media limit. |
| Multiple moment discovery | Present | Deterministic transcript-driven discovery emits rich candidates with context, rationale, hook/title, confidence/warnings, and temporal duplicate suppression. |
| Human selection | Present | Preview, approve, reject, trim, title/hook editing, and sensitive/unsuitable decisions are append-only. Rendering fails closed without current approval. |
| Vertical rendering | Partial | Approved clips render as 1080×1920 safe padded compositions using the existing trim/resize/audio engines. Subject-aware crop-track lowering exists and is tested, but the orchestrator does not yet execute it automatically. |
| Captions | Present, quality depends on transcription | Every rendered draft gets editable phrase-grouped SRT. Burn-in is optional and off by default. Low-confidence policy never synthesizes replacement words. |
| Audio finishing | Partial | Loudness normalization, true-peak limiting, and 50 ms boundary fades are applied. Optional noise reduction remains bypassed by default. Human boundary listening is still required. |
| Export packages | Present | Each approved platform draft packages vertical video, editable SRT, thumbnail, drafting metadata/source timestamps, lineage, and a machine-readable manifest. |
| Restart/rerender | Present for saved plans and unchanged renders | Plans persist as JSON; source checksum is revalidated; unchanged approved render digests return cache hits without retranscription. |
| Public posting/authentication | Out of scope | No posting, account, scheduler, CMS, SEO, or analytics-dashboard surface exists. |

## Install local transcription

```bash
uv sync --frozen --extra transcribe --extra dev
```

A cloud provider is optional and must be configured by the operator. The local/offline path remains the default.

## Canonical guided workflow

### 1. Propose clips; do not render

```bash
uv run --frozen kino --format json shorts /path/to/recording.mp4 \
  --platform youtube-shorts \
  --platform instagram-reel \
  --min-clip-seconds 15 \
  --max-clip-seconds 60 \
  --captions-editable \
  --output-dir ./out/shorts
```

The response includes a job id and candidate list. The command stops for review.

### 2. Record human decisions

Create `decisions.json` using candidate ids from the proposal:

```json
{
  "decisions": [
    {
      "proposal_id": "candidate-id",
      "decision": "trim",
      "edit": {"action": "trim", "start": 120.5, "end": 153.0},
      "evidence_ref": "operator-review"
    },
    {
      "proposal_id": "candidate-id",
      "decision": "approve",
      "evidence_ref": "operator-review"
    }
  ]
}
```

Record the review from the exact saved plan without rendering or reopening the source media:

```bash
uv run --frozen kino --format json shorts \
  --resume-job-id shorts_JOB_ID \
  --decisions decisions.json \
  --output-dir ./out/shorts
```

Both `--resume-job-id` and `--output-dir` are required. Together they identify the single saved plan at `./out/shorts/shorts_JOB_ID.plan.json`; editorial review does not require the original recording path or rerun transcription. Other supported decisions are `preview`, `reject`, `title_hook_edit`, and `sensitive_unsuitable`.

### 3. Render the approved candidate

```bash
uv run --frozen kino --format json shorts --render \
  --resume-job-id shorts_JOB_ID \
  --candidate-id candidate-id \
  --output-dir ./out/shorts \
  --output ./out/shorts/rendered
```

Rendering fails closed unless the candidate has current approval. Inspect the vertical framing, captions, and audio boundaries; the command does not claim subject-aware framing or completed human audio review.

### 4. Package the rendered candidate

```bash
uv run --frozen kino --format json shorts --package \
  --resume-job-id shorts_JOB_ID \
  --candidate-id candidate-id \
  --output-dir ./out/shorts \
  --output ./out/shorts/package
```

The package is a local artifact for manual publishing. These commands use the shared `shorts_render` and `shorts_package` functions, do not authenticate, and never post publicly.

## Configuration defaults

- Platforms: YouTube Shorts and Instagram Reels
- Editable subtitles: enabled
- Burned captions: disabled
- Loudness target: −14 LUFS
- True peak: approximately −1.0 dBTP
- Boundary fade: 50 ms
- Noise reduction: bypassed
- Subject tracking unavailable/uncertain: safe padded composition, requiring manual framing review

## Error format

Workflow errors state the problem, likely cause, and recovery action. Examples include missing audio, unreadable media, missing transcription runtime, no complete candidates, changed source checksum, missing approval, and unsuitable content.
