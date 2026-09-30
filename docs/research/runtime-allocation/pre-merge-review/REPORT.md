# Pre-merge review corrections for PR #586

The final inline-review pass on head `5d3c4317c748b94fa4280259fdc759945f114fce`
identified six actionable findings despite all thirteen checks passing on that
head. The user explicitly authorized merging #586; these corrections precede
the merge and require fresh exact-head CI evidence.

| Review finding | Correction and evidence |
| --- | --- |
| [Stale audit manifest raised a raw error](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075083) | Structured `MCPVideoError`, validation type and `stale_audit_manifest` code. A regression checks serialized error fields. |
| [Audit entry point exceeded function-size rules](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075104) | Extracted inventory collection and report publication; all audit functions fit the 80-line limit. Working-tree/HEAD fixture tests preserve allocation, inventory, JSON and CSV contracts. |
| [Retained source audio lost its offset](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075115) | Rebase primary picture to zero with `-copyts` and source input offset; timestamp-aware resampling retains source audio alignment. Real early/late audio fixtures check silence, audible positions and identical decoded picture frames. |
| [Longer container audio extended the picture timeline](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075126) | Use selected picture stream duration, with bounded selected-packet extent fallback when metadata is insufficient. MP4/MKV controls preserve the two-second picture despite five-second source audio and reject starts beyond picture end. |
| [Mixer omitted promised staged decode](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075133) | Require expected AAC and a bounded error-failing primary-audio decode before atomic publication. Actual AAC packet corruption preserves the prior destination and cleans staging. Normalization retains its existing full-decode default. |
| [Advertised normalization suffixes failed staging](https://github.com/KyaniteLabs/kinocut/pull/586#discussion_r4147075149) | Add `.ogg`, `.opus`, `.aif` and `.aiff` to the existing shared output allowlist. Eight real cases cover new/existing destinations, actual codecs/containers, stereo 48 kHz, complete audio decoding and cleanup. |

The four initial real mixer timeline controls failed before the correction and
passed afterward. The final focused mixer/normalization/client-contract set
passed **73 tests in 39.31 seconds**. Root's normalization suffix set passed
**8 tests in 5.60 seconds**; the audit regressions passed **4 tests**. These counts
overlap the required full suite and are not additive acceptance totals.

The mixer still stream-copies picture and performs one AAC encode. Staged decode
adds a separate bounded read/decode pass. Missing picture metadata may require
bounded demuxing: at most 1,000,001 selected video packets including an overflow
sentinel, with more than 1,000,000 rejected. Metadata above 64 MiB is rejected
after producer completion and before streaming parsing; the size check is not a
hard transient file-size cap. Every packet record counts before parsing, and
unknown presentation timestamps/durations fail explicitly. Dense interleaved
audio tests verify that the tested FFprobe's producer cap counts selected video
packets instead of silently certifying an early partial extent.

An additional primary FFprobe 6.1 check passed **5 tests, 34 deselected, in 3.11
seconds**: both source-audio offsets, both MP4/MKV picture-tail cases and the
dense-interleaving producer cap. It used official pinned source
`d4ff0020b40b524a490cf62eccbd3a318f4c0e58`, with MOV/WAV demuxers and
H.264/AAC/PCM decoding added to the earlier minimal local probe build. Encoding,
mixing and staged decoding still used FFmpeg 7.1.5. The first attempted run
failed five initial probes because that minimal build lacked the needed
demuxers; those were setup failures, followed by the component-enabled passing
run. This is a scoped FFprobe comparison, not a full FFmpeg 6 platform gate.

No new learned backend, inference benchmark or universal latency improvement is
claimed. The allocation report measures source units, not runtime activity,
quality, model frequency, token usage or cost. Earlier grayscale and full-suite
checkpoints remain under `iteration-3/`; this directory records the later review
corrections separately.

## Completed local gate and source snapshot

Implementation `cfdf03a3b8fb59aa285e7a20509518b2503c4660` passed the required
full suite: **7,451 passed, 185 skipped, 8 warnings**, exit 0, in 936.30 seconds.
[Structured result](validation.json) includes eight frozen source hashes;
[full log](full-suite.log) retains the completed output. Ruff 0.15.11 check and
format passed the expanded 1,073-file scope, alongside import identity and
module/function limits. Exact published-head CI remains separate evidence on
the [PR checks page](https://github.com/KyaniteLabs/kinocut/pull/586/checks).

[Allocation](allocation.json) covers 625 runtime source files: **96.9369%
deterministic, 2.6338% operational LLM prose and 0.4293% non-LLM ML**, totaling
100%. Runtime proportions changed through intentional deterministic timing and
validation code; no prose or model lane was added to manufacture a target share.
