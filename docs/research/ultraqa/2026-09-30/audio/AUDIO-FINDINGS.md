# Audio implementation and independent temporal review

Runtime and test ownership frozen: engine_audio_normalize.py, engine_audio_mix.py, engine_audio_ops.py; new engine_audio_validation.py and engine_media_timeline.py; appended AUDIO_NORMALIZE/AUDIO_DUCK validation constants; associated audio tests. No commits or GitHub writes by this agent.

## Implemented behavior

- Normalization explicitly analyzes and renders primary 0:a:0; selected stream metadata determines rate/duration/fades, even when a later audio stream is default. Primary optional picture retained for video outputs.
- Boundary fades account for selected audio origin relative to FFmpeg demux container origin. Delayed source audio tails remain audible; audio-only output removes leading container gaps while preserving selected audio extent.
- Loudnorm input ranges match backend I[-70,-5], LRA[1,50], TP[-9,0]. Shared strict finite numeric validation rejects booleans, wrong types, NaN/infinity and integer conversion overflow before rendering.
- Mixer always measures primary picture presentation packet extent. Positive MP4 stream.duration is no longer assumed to be actual picture presentation duration: reordered VFR B frames can lie beyond it. Picture remains stream-copied; original audio timing is preserved.
- Added tracks use selected a:0 audio extent rather than longer picture/container extent. Fades apply to the audible clipped segment. For audio without usable stream duration, bounded FFprobe frame decoding measures samples, with a packet producer sentinel counted independently from decoded frames; AAC priming packets with missing duration remain supported.
- Attachment and ducking reject missing/empty primary audio while accepting genuine measured silence. Strict numeric validation precedes comparisons/filter construction; duck threshold matches backend minimum1/1024. Existing signatures and intentional duration policies retained, with explicit primary audio maps.
- Attachment and ducking stage output, validate actual AAC/full primary-audio decode, and construct the result before atomic publication. Encoding, decode and receipt failure preserve prior destination. All four selected-audio render/analysis paths use -xerror so corrupt AAC cannot be silently concealed as successful processing.

## Bounds and costs

Shared timeline extraction uses existing named 1,000,000 packet and64MiB metadata bounds, FFprobe deadline, sentinel+1 producer, constant-memory parsing, and before/after file stat identity. Frame fallback also limits decoded frame records; every producer packet counts even if a decoder returns no frame. Byte bound is checked after FFprobe writes metadata, so it is not a hard transient disk peak cap. Stat identity is not a cryptographic snapshot or a whole-operation source immutability guarantee.

Mixer now does presentation metadata extraction even when a video has duration metadata. Audio lacking a usable duration adds a bounded source-audio decoding pass. Attachment/ducking now add staged audio validation decode. These costs intentionally strengthen correctness; no universal latency improvement claimed. Mixer still performs one AAC encoding.

## Validation

Before environment refresh: final combined focused suite230passed,1skipped in144.76s, covering mix, loudnorm, fades, suffixes, new temporal/source formats, timeline bounds, new attachment/duck boundaries, input kinds, duration policies, client aliases and public surfaces. Module/function800/80 bounds and Ruff check/format passed. The one skipped parameter matrix cell is start_time=None, which intentionally means no delay rather than an invalid number; valid default delay is covered separately.

After environment refresh and root's descriptor-backed publication changes: scoped temporal/source-format + attachment/duck + timeline tests87passed,1skipped in52.52s. Full log: final-audio-boundaries.log. Source formats include8-bit PCM8k mono,24-bit PCM32k stereo, float PCM48k5.1; normalization retains channels/rate and mixing emits48k stereo.

Actual official FFmpeg6.1 render/probe/decode was exercised before /tmp reset using KINOCUT_FFMPEG_EXECUTABLE/KINOCUT_FFPROBE_EXECUTABLE, not a runner-only instrumentation patch: temporal/timeline17passed,3deselected in4.94s. Generators and RMS remained installed7. Native6 FFmpeg SHA256 b7542bb856e51554ade492dfb3d00c71758b847007eae08ef2a4a66cb36fe615; FFprobe cba282ef3f99856e7df498a6c067c644b94e3c1e0d122915c4337c215c101d6e. These historical binaries/logs are gone after environment refresh. Build lacked sidechaincompress and24-bit source decoding; no coverage claim for those components. Exact final-head hosted6CI is needed for root's later descriptor writer changes.

## Independent root-owned findings — no edits

1. **Confirmed temporal fade bug:** white picture1s/audio1s, fade_out.5 -> YAVG51 at.9s. Identical picture1s/audio3s -> YAVG235 unchanged because fade is scheduled2.5s from container duration. Also picture atPTS1..2/audio0..3, fade_in.5 -> YAVG235 at1.08s, because effect was scheduled0. Repro and actual metadata/pixel evidence: fade_review.py/.json and local media.
2. **Confirmed exact crop mismatch:** request81×45 on160×90 YUV420 picture returns successful80×44. FFmpeg's default crop chroma rounding silently changes requested dimensions. Repro: core_geometry_review.py/.json.
3. **Observation, not visual-distortion claim:** rotated90-degree source preview is encoded320×240 withSAR27:64/DAR9:16, so portrait display aspect is preserved despite landscape coded dimensions. Source rotation precondition verified using-display_rotation. This should be considered an explicit anamorphic preview/display-coordinate policy, rather than assuming rotation is lost.

Independent read of root's staged descriptor rewrite/publication pattern found no additional concrete bug; media tests exercise seekable MP4/AAC descriptor output, postflight and publication. No Windows execution claim.

## Untouched/unproven boundaries

Governed audio_bed attempted real long-audio-picture and short-audio-music fixtures, but production fails closed because this host lacks fcntl F_ADD_SEALS/F_SEAL_* constants. Did not bypass snapshots. Its container-duration selection remains a static temporal concern; no complete governed render proof claimed. Reverse whole-container versus independent stream reversal with differing stream extents is an unresolved policy boundary, not asserted as a proven defect. No exhaustive all-operations quality, listening, resource-peak or production-delivery claim.

## Final attachment and rescue follow-up

Attachment fades now follow actual added audio origin plus the existing millisecond-quantized requested delay, and end at the earlier of actual sound end and primary-picture presentation end. Looped audio fades at the final picture window. Timestamp-aware resampling explicitly materializes source/added leading gaps before amix, preserving native audible offsets. Six real controls (requested delay, native delay, looping × replace/mix) pass. Attachment-related focused gate160passed,1intentionalNone-delaymatrixskip in152.39s (`attachment-final.log`).

Rescue verification's original duration/two-frame tolerance is unchanged; inclusive comparisons allow only a rounding budget from the operand ULPs. Duration, AV endpoint and caption comparisons use the same rule. Decimal boundary3.1−3.0 succeeds; measured overruns of1e-9s beyond the boundary still fail. Verifier/renderer24tests passed50.25s (`rescue-boundary.log`). Cancellation fixture now cancels after its explicitly named metadata repair and proves that operation completed with a matching artifact hash, since truthful capabilities can schedule an audio repair first; no renderer weakening.

The initial ULP refactor renamed a private helper shared by body-swap; full collection caught this integration mistake. Restored `_av_end_delta` as a compatibility wrapper over the single shared endpoint parser, with difference/missing-stream regression. Final verifier+aivideo protection42tests passed4.28s (`verifier-compatibility.log`), whole-suite collection8181tests succeeded4.71s (`all-tests-collection.log`). Source and tests are refrozen; parent owns the authoritative full suite and delivery.
