# Video Rescue

The dedicated rescue pipeline diagnoses and repairs one local video without changing its
story, timing, or source file. It is deliberately review-first: plan, inspect, approve safe
repair IDs, render, then inspect the verified package.

## Safety Contract

- **Local-only:** diagnosis, rendering, optional transcription, and verification run locally.
- **Source immutable:** the source is read-only and its SHA-256 must remain unchanged.
- **Timeline locked:** rescue does not cut, reorder, retime, synthesize, crop, reframe, or
  replace content.
- **Captions are not burned:** optional captions and transcripts are package sidecars.
- **Missing Whisper is nonfatal:** the package records captions and transcript as unavailable
  with a reason while master and sharing copy can still succeed.
- **Plan approval is required:** inspect the plan before rendering and approve only IDs from
  its `safe_repairs` list.
- **No one-command rescue:** there is intentionally no `rescue` shortcut that diagnoses and
  renders without the review boundary.

Planning and inspection do not render final media. Rendering fails closed if the source,
plan, policy, dependency versions, approvals, or reusable intermediates no longer match.
Cancellation or a gating verification failure never promotes a package.

## CLI

```bash
mcp-video rescue-plan --source media/clip.mov --output-dir rescue-output --save-plan rescue-output/plan.json
mcp-video --format json rescue-inspect --receipt rescue-output/plan.json
mcp-video rescue-render --plan rescue-output/plan.json --approve rotation:metadata --approve audio_loudness:primary --save-receipt rescue-output/render-receipt.json
mcp-video rescue-inspect --receipt rescue-output/render-receipt.json
```

Review `safe_repairs`, `recommendations`, `unavailable_repairs`, `blocked_repairs`, previews,
package intents, capabilities, and the estimate before `rescue-render`. Repeating `--approve`
selects exact safe repair IDs. Omitting `--approve` approves every policy-classified
`safe_repair` ID in the already reviewed plan; it never approves recommendations.

Cancellation and resume are explicit:

```bash
touch rescue-output/cancel
mcp-video rescue-render --plan rescue-output/plan.json \
  --cancel-file rescue-output/cancel \
  --save-receipt rescue-output/cancelled.json

rm rescue-output/cancel
mcp-video rescue-render --plan rescue-output/plan.json \
  --resume rescue-output/cancelled.json \
  --save-receipt rescue-output/render-receipt.json
```

The renderer checks the cancellation marker between stages. Resume requires matching source,
plan, policy, MCP Video, FFmpeg, approved repair IDs, and hashes for all reused intermediates.
`--keep-intermediates` retains managed work files for diagnosis; successful renders otherwise
clean them.

## MCP

The MCP tools expose the same contract:

1. Call `video_rescue_plan(source, output_dir, save_plan)`.
2. Present and inspect every disposition and preview.
3. Call `video_rescue_render(plan, approved_repair_ids, save_receipt, resume_receipt,
   cancel_file, keep_intermediates)` with only approved safe IDs.
4. Call `video_rescue_inspect(receipt)` and report package integrity and gating checks.

An `unavailable` item is an honest capability or applicability result, not automatically a
failed rescue. Never add recommendation or blocked IDs to `approved_repair_ids`.

## Python

```python
from mcp_video import Client

video = Client()
plan = video.rescue_plan(
    "media/clip.mov",
    "rescue-output",
    save_plan="rescue-output/plan.json",
)

# Present and review plan["safe_repairs"], the other disposition buckets,
# preview_artifacts, package_intents, capabilities, and estimate here.
approved = [repair["id"] for repair in plan["safe_repairs"]]

receipt = video.rescue_render(
    "rescue-output/plan.json",
    approved_repair_ids=approved,
    save_receipt="rescue-output/render-receipt.json",
)
inspection = video.rescue_inspect("rescue-output/render-receipt.json")
```

The Python methods are `Client.rescue_plan`, `Client.rescue_render`, and
`Client.rescue_inspect`. They return the same structured dictionaries used by MCP and JSON CLI
output.

## Dispositions

| Disposition | Meaning | Executable by rescue |
|---|---|---|
| `safe_repair` | Bounded, local, content-preserving action allowed by the embedded policy | Yes, after plan review |
| `recommendation` | Potentially useful work requiring creative or contextual judgment | No |
| `unavailable` | Repair cannot run with the current local media or capability set | No; not itself a pipeline failure |
| `blocked` | Action violates the local content-preserving or timeline-lock policy | No |

The analyzer records evidence and bounded parameters. Policy code alone assigns these
dispositions. The renderer consumes plan IDs, never raw FFmpeg or filter fragments.

## Repair Catalog

The version 1 schema recognizes rotation, container timestamps, metadata, universal MP4,
audio loudness, audio denoise, exposure, white balance, captions/transcript, stabilization,
reframe, timeline edit, synthetic content, and cloud processing. Availability and disposition
depend on measured evidence and policy. Timeline edits, synthetic content, cloud processing,
and other story-changing work are never silently promoted into automatic repair.

## Package And Verification

Every successful video rescue promotes:

- a high-quality `master`;
- a universal H.264/AAC-or-silent MP4 `sharing_copy`;
- a hashed rescue receipt;
- `captions.srt` and `transcript.txt` when verified local Whisper is available, otherwise
  explicit unavailable artifacts with `missing_local_whisper` or `no_audio_stream`.

Verification fully decodes both video outputs and checks source immutability, duration delta,
monotonic timestamps, stream coverage, A/V end-time delta, caption bounds, spoken-text
coverage, the universal MP4 contract, explicit metric units, and persisted hashes. Numeric
metrics include a name, value, unit, definition, and availability status.

`receipt_sha256` is the SHA-256 of the finalized canonical receipt payload, excluding only
the two self-referential digest slots: the top-level `receipt_sha256` value and the receipt
artifact's own `sha256` value. The packaged receipt and any `--save-receipt` copy are
identical, and inspection recomputes this digest before trusting the package manifest.

## Stable Errors

Automation may branch on these error codes:

- `invalid_rescue_input`, `invalid_rescue_plan`, `invalid_rescue_receipt`
- `rescue_source_mismatch`, `rescue_plan_mismatch`, `rescue_policy_violation`
- `rescue_approval_invalid`, `rescue_dependency_mismatch`, `rescue_intermediate_mismatch`
- `rescue_cancelled`, `rescue_verification_failed`, `unsafe_rescue_output`

CLI commands exit nonzero for structured rescue failures. Verification failures remain in a
quarantined package for inspection rather than appearing as successful output.

## Optional Whisper

Whisper remains optional and is never downloaded by rescue. Install it manually when local
caption sidecars are wanted:

```bash
pip install "mcp-video[transcribe]"
```

The configured local model must already exist and match the planned digest. Run
`mcp-video doctor` to see `rescue.core_ready` and `rescue.captions_available`.

## Compatibility And Performance

The three rescue tools, commands, and client methods are additive. Existing editing,
workflow, compositor, quality-check, and Hyperframes APIs are unchanged. The sharing copy is
an additional artifact. Intentional 24 fps delivery behavior elsewhere in MCP Video is
unchanged.

Performance receipts for a 60-second 1080p synthetic fixture record cold and warm planning
wall time, CPU, memory, OS, FFmpeg version, clip properties, enabled analyzers, sample limit,
local model availability, predicted seconds, actual seconds, and absolute estimate error. The
planning target is approximately 30 seconds, but elapsed time is reported rather than used as
a heterogeneous-hardware test failure. Diagnosis remains bounded by the configured sample
limit.
