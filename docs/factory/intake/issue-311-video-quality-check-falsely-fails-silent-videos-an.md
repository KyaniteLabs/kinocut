        # Factory intake for issue #311: video-quality-check falsely fails silent videos and renders empty report

        Repository: `KyaniteLabs/mcp-video`
        Category: `llm_fix`
        Source issue: `#311`

        ## User request

        ## Bug

`mcp-video video-quality-check` gives a misleading empty `Overall: FAIL` report for valid silent videos.

This has now blocked/derailed the NucBox image-to-video workflow repeatedly. On the latest run, a valid 1080x1920 / 30fps / 61-frame silent MP4 was marked FAIL with an empty table, even though visual QA and Kimi review showed the clip was visually usable.

## Latest reproduction evidence

Command run on the NucBox:

```bash
/srv/external/bin/mcp-video video-quality-check \
  /srv/external/generated-output/kyanite-puenteworks-local-gen-2026-05-19/2026-05-21-real-i2v-ltx-gemma-512x896-49f-20260521T044307Z/pw-ltx-gemma-final-1080x1920-30fps-grade.mp4
```

Observed output:

```text
[05/21/26 04:57:36] WARNING  ffmpeg loudnorm returned no JSON payload for .../pw-ltx-gemma-final-1080x1920-30fps-grade.mp4

      Quality Check
┏━━━━━━━┳━━━━━━━━┳━━━━━━━┓
┃ Check ┃ Status ┃ Value ┃
┡━━━━━━━╇━━━━━━━━╇━━━━━━━┩
└───────┴────────┴───────┘
Overall: FAIL
```

ffprobe for the same file:

```text
width=1080
height=1920
avg_frame_rate=30/1
duration=2.033333
nb_frames=61
```

Final Kimi visual review confirmed the clip had no major visual artifacts and the quality issue was about motion level/duration, not container validity or audio failure.

## Likely root causes

There appear to be two related bugs:

1. Silent/no-audio handling in `mcp_video/quality_guardrails.py`:
   - `_analyze_loudnorm()` returns a truthy `{"_error": ...}` when ffmpeg loudnorm produces no JSON.
   - `check_audio_levels()` only runs the no-audio `ffprobe -select_streams a:0` branch when `not loudness_data`.
   - Because the error dict is truthy, silent videos can be treated as failed audio analysis instead of `passed=True`, `has_audio=False`, `message="No audio stream detected in video"`.

2. CLI formatting in `mcp_video/cli/formatting.py`:
   - `_format_quality_check()` expects `checks` to be a dict and `passed` to be present.
   - `quality_check()` actually returns `checks` as a list and `all_passed` as the overall boolean.
   - Result: the table renders empty and `Overall: FAIL` even when the API report contains structured check rows.

## Expected behavior

For a valid silent video:

- `video-quality-check` should detect there is no audio stream before/after loudnorm failure.
- Audio check should pass or be marked skipped with `has_audio: false`, not fail the whole report.
- CLI output should render all checks from the returned list schema.
- Overall status should use `all_passed`, not missing `passed`.
- If an audio stream is absent, warnings should be explicit and non-fatal unless the caller requested an audio-required mode.

## Acceptance criteria

- Add regression coverage for a valid silent MP4.
- `quality_check(silent_video)` returns an audio check with `passed=True` or explicit skipped status and `details.has_audio == false`.
- CLI `mcp-video video-quality-check silent.mp4` shows non-empty rows.
- CLI overall status reflects `all_passed` from the API result.
- Loudnorm mis

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
