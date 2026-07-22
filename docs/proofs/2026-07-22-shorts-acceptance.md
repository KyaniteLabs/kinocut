# Long-form stream-to-shorts acceptance receipt — 2026-07-22

## Status

**PARTIAL.** The current real-media run completed intake, chunked transcription, discovery, human adjustment, approval-gated rendering, packaging, and saved-plan rerender. Production readiness remains blocked only by required human listening at every edit boundary. Safe padded framing also remains an explicit operator-review warning rather than a polished subject-aware crop.

## Source and provenance

- Recording: *BBS Documentary Interview: John Sheetz*
- Source page: <https://archive.org/details/20030322-bbs-sheetz>
- License: CC BY-SA 2.5
- Original recording: `/tmp/kinocut-acceptance/bbs-sheetz-60min-640x480.mp4`
- Original duration: 3598.864 seconds
- Over-hour branch fixture: `/tmp/kinocut-acceptance/bbs-sheetz-over-hour.mp4`
- Fixture construction: the unchanged complete recording followed by six seconds copied from its opening, solely to exercise the `>3600` chunked-transcription branch with real licensed media.
- Fixture duration: 3604.983 seconds
- Resolution: 640×480
- Audio: AAC present
- Fixture SHA-256 before and after processing: `8649d2558256e0ecf5d01896aeddf43b9031c6b1abe107829924f3126ccfbfbc`
- Original and fixture media were unchanged by Kinocut.

## Canonical CLI run

Proposal command:

```bash
uv run --frozen --extra transcribe kino --format json shorts \
  /tmp/kinocut-acceptance/bbs-sheetz-over-hour.mp4 \
  --platform youtube-shorts \
  --platform instagram-reel \
  --min-clip-seconds 15 \
  --max-clip-seconds 45 \
  --captions-editable \
  --output-dir /tmp/kinocut-acceptance/over-hour-cli-out-wordtimed
```

Result:

- Job: `shorts_71708b201d95e186`
- Status: `review_required`
- Chunked long-form path: exercised
- Transcript segments: 745
- Real Whisper word timings retained: 9510
- Distinct candidates: 6
- Receipt: `/tmp/kinocut-acceptance/over-hour-summary.json`
- Full response: `/tmp/kinocut-acceptance/over-hour-cli-wordtimed-result.json`

The local Whisper model produced recognizable but imperfect wording. Low-confidence words remain marked `[?]`; Kinocut did not invent replacements.

## Human review actions

- Adjusted candidate: `seg_000186-5f7df3`
  - final source range: 1161.68–1184.32 seconds
  - title: “How Early Online Communities Got Connected”
  - hook: “Before modern internet access, getting connected took special arrangements.”
- Approved candidates:
  - `seg_000186-5f7df3`
  - `seg_000231-e7f332`
- Saved edit replay: `/tmp/kinocut-acceptance/over-hour-adjustment-result.json`
- Rendering remained fail-closed until approval records existed.

## Rendered drafts

Four current 1080×1920 H.264/AAC drafts:

1. `/tmp/kinocut-acceptance/over-hour-rendered/seg_000186-5f7df3/youtube-shorts/vertical.mp4`
2. `/tmp/kinocut-acceptance/over-hour-rendered/seg_000186-5f7df3/instagram-reel/vertical.mp4`
3. `/tmp/kinocut-acceptance/over-hour-rendered/seg_000231-e7f332/youtube-shorts/vertical.mp4`
4. `/tmp/kinocut-acceptance/over-hour-rendered/seg_000231-e7f332/instagram-reel/vertical.mp4`

Measured results:

- Integrated loudness: −14.30 to −14.53 LUFS
- True peak: −0.95 to −0.71 dBTP
- AAC encoding overshot the configured −1.0 dBTP target by at most 0.29 dB; every measured peak remained below 0 dBTP, so no automated clipping was detected.
- A/V duration delta: 0.077–0.091 seconds
- Full report: `/tmp/kinocut-acceptance/over-hour-audio-video-report.json`
- Boundary fades are applied before final two-pass loudness normalization.
- Repeating the adjusted candidate render returned cache hits for both platforms: `/tmp/kinocut-acceptance/over-hour-rerender-v5.json`.

## Visual and caption inspection

Beginning, middle, and end were directly inspected for every current draft:

- `/tmp/kinocut-acceptance/over-hour-inspection/seg_000186-5f7df3-youtube-shorts-sheet.jpg`
- `/tmp/kinocut-acceptance/over-hour-inspection/seg_000186-5f7df3-instagram-reel-sheet.jpg`
- `/tmp/kinocut-acceptance/over-hour-inspection/seg_000231-e7f332-youtube-shorts-sheet.jpg`
- `/tmp/kinocut-acceptance/over-hour-inspection/seg_000231-e7f332-instagram-reel-sheet.jpg`

The face and hands remain visible at every sampled point; no primary subject is cropped out. Conservative safe composition introduces large black padding above and below the 4:3 source, so framing remains flagged for manual review.

Editable SRT examples:

- `/tmp/kinocut-acceptance/over-hour-rendered/seg_000186-5f7df3/youtube-shorts/captions.srt`
- `/tmp/kinocut-acceptance/over-hour-rendered/seg_000231-e7f332/youtube-shorts/captions.srt`

Cues are monotonic, bounded to effective clip time, and derived from real Whisper word timestamps. Recognition errors and low-confidence markers remain editable.

## Export packages

Complete YouTube Shorts and Instagram Reels packages:

- `/tmp/kinocut-acceptance/over-hour-packages/seg_000186-5f7df3/`
- `/tmp/kinocut-acceptance/over-hour-packages/seg_000231-e7f332/`

Every platform directory contains `vertical.mp4`, `captions.srt`, `thumbnail.jpg`, and `pkg_*__manifest.json`. Manifests contain drafting-only title/description metadata, effective source timestamps, candidate rationale/context, transcript/source lineage, and render digest. They make no engagement, ranking, or virality claim.

## Automated verification

- Focused remediation suites: 215 passed, then 136 passed after the second adversarial review fixes.
- Final full repository suite: **4576 passed, 172 skipped** in 513.42 seconds.
- Ruff passed across `kinocut`, `tests`, and `scripts`.
- All changed Python files pass `ruff format --check`.
- `git diff --check` passed.
- `scripts/collect_usage_metrics.py` is pre-existing and not Ruff-format-clean; it was left unchanged as unrelated work.

## Remaining acceptance blocker

No available tool provides trustworthy human auditory perception. Automated loudness, true-peak, A/V duration, and fade checks passed, but every current edit boundary has not been human-listened. This receipt therefore cannot claim DONE or production-ready status.

Human-ready listening pack:

- directory: `/tmp/kinocut-acceptance/over-hour-boundary-listening-pack/`
- playlist: `/tmp/kinocut-acceptance/over-hour-boundary-listening-pack/playlist.m3u`
- checklist: `/tmp/kinocut-acceptance/over-hour-boundary-listening-pack/index.json`
- clips: 8 WAV files covering both boundaries of all four current drafts

For each clip, record pass/fail for pops or clicks, clipped syllables, abrupt discontinuities, and unexpected silence.
