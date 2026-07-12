# AI-video review and salvage operating guide

This guide covers the current governed Wave 3 workflow. These operations create evidence and
derivatives; they do not publish media or replace human creative review.

## Safe operating sequence

1. **Ingest the exact source bytes.** `video_ingest` copies the original into the private
   content-addressed project store and returns the authoritative `asset_id`.
2. **Inspect before deciding.** Run `video_preflight` and `video_inspect_temporal`. Review the
   audible/muted previews, motion strip, late frames, declared-region crops, integrity findings,
   and optional-provider availability.
3. **Create the acceptance contract.** Record objective requirements and the exact required human
   evidence. Do not manufacture acceptance evidence from analyzer output.
4. **Record the human decision.** The decision must be active, target the exact artifact, name the
   reviewer role, and bind the required evidence artifact.
5. **Persist a verdict.** `video_verdict` accepts analysis dispositions, but an approved
   disposition fails closed unless the exact active human evidence satisfies the acceptance spec.
6. **Declare protected elements.** Protect approved source assets, audio streams, clip ranges,
   subtitles, graphics, timing maps, mixes, and render parameters before mutation.
7. **Choose one bounded derivative.** Use `video_body_swap` to replace picture while preserving
   approved audio, or `video_salvage` for an allowlisted salvage recipe. There is no force or
   bypass flag.
8. **Inspect the derivative as new work.** Every salvage derivative has lineage and starts in a
   fresh non-approved review slot. Re-run preflight, temporal inspection, and human review.

## Body swap policies

- The default policy rejects a duration mismatch.
- `pad_video` may extend replacement picture while preserving approved audio.
- `trim_video` may shorten replacement picture while preserving approved audio.
- `trim_audio` is explicitly audio-changing and must never claim exact audio identity.

Exact-preservation policies prove complete encoded audio-stream identity and stream topology after
render. Inputs and outputs may not alias the same file, including hard links.

## Salvage recipes

Recipes are allowlisted and policy-bound. They operate on verified stored snapshots, never on an
ambient path supplied after authorization. Each result records source lineage, transformation,
output hash, preservation evidence, and the new review state.

Use the smallest recipe that addresses the evidenced defect. A crop or still-frame repair must not
be generalized into approval for unrelated timing, audio, subtitle, graphic, or mix changes.

## Failure means stop

Stop when an asset is missing or ambiguous, a stored source no longer matches its identity, a
protected dependency would change, human evidence is absent/stale, a preservation proof cannot be
computed, or an output fails post-render validation. Do not work around these failures with raw
FFmpeg and then label the result governed.

## Surface parity

The MCP tools, Python client, and flat CLI commands call the same adapters. See
[MCP tools](TOOLS.md), [Python client](PYTHON_CLIENT.md), and [CLI reference](CLI_REFERENCE.md).
