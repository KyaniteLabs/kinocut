# Explicit source sample-rate conversion

V4 supplied mixes convert clips, the optional bed and every ambient layer to
`plan.format.sample_rate_hz` before source trimming or mixing. Python, CLI and MCP
use the existing `sound_mix_render` operation. Import `SoundMixRequestV4` and
`SourceResampling` from `kinocut_sound.public`.

Extend a valid V3 request (or a routed request with `layer_assets: []`) with:

```json
{
  "schema_version": 4,
  "source_resampling": {"profile": "soxr_vhq_pcm16_guarded_v1"}
}
```

The profile is required and closed; unknown options are rejected. Source and
target must be mono/stereo PCM16 WAV with the same channel count, at integer rates
from 8–96 kHz. The plan remains continuous-time, without dither or channel
conversion. A downmix preset does not authorize upmix or rate conversion.

Rate changes require FFmpeg built with libsoxr. The profile fixes precision 28,
cutoff 0.91, Chebyshev mode off, dither off, and one decoder/filter thread. There is
no fallback to another resampler. Same-rate sources are copied byte-for-byte and
need no backend. Original source hashes always bind the original complete WAVs.

## Exact frames and composition

Let S be original frames, p the source rate and q the target rate. The target count
T is the exact rational S*q/p rounded to nearest, with ties to even. A zero-frame
target fails before conversion. Native resampler tie behavior can vary by ratio,
so the profile explicitly appends G=ceil(p/q) zero input frames before resampling.
The resulting raw count must be floor or ceil of (S+G)*q/p and at least T. Only the
first T frames are retained. Derived output is never padded to hide a short result.

Cue in/out seconds and crossfade post-roll are then quantized at the target rate.
Layer crossfade lengths remain explicit target-rate frame counts. Automation,
loop/pad layers, bed/layer ducking, pre/post-fader sends and final bus sidechains
operate on the normalized PCM. Distinct layers may share one asset; they retain
separate layer-ID bindings and processing.

## Evidence and ownership

V4 uses receipt schema 5 and `request_schema_version: 4`. The `source_resampling`
section records each role, original path/hash/shape, derived hash/shape, profile,
backend version/settings, input guard, raw frames and discarded suffix frames.
Private derived filenames and manifest paths are excluded. Same-rate entries use
`mode: copy`, equal original/derived hashes, and no backend record.

Results add `resampling_profile`, `converted_source_count` (rate-changed bindings),
and `resampling_sha256` over the canonical public section. The parent independently
checks original and derived bytes/shapes, all clip windows including clips without
automation, bed/layer evidence and routing constraints before publication. It does
not independently re-run acoustic DSP. Human listening and mastering remain
separate acceptance steps.

Converters are sequential direct children of the parent. The mix worker remains
pure Python. Raw output streams to a bounded private sink. Timeout, overflow,
malformed output, cancellation or cleanup failure cannot publish a final archive.
Private conversion storage is removed before exclusive publication. Existing files
are never overwritten. This retains the supplied-mix POSIX filesystem boundary;
it does not add Windows support or kernel-immutable files.

## Limits

Original and derived inputs each have a 256 MiB total cap; every role counts,
including repeated assets. Manifest/public conversion metadata is capped at 1 MiB.
Conversion work is capped at 256 million structural units: C*(S+G+U)+65,536 per
changed binding, where U is its maximum raw frame count, or C*S per same-rate copy.
Existing routed-feature limits remain separate and enforced.

Admission conservatively accounts for complete input/decoded/raw/WAV buffers,
native workspace, metadata and IPC under the existing 2 GiB memory estimate.
These reservations are not measured or hard RSS guarantees. Media work shares a
300-second deadline, checked between parent phases; cleanup retains ownership of
an in-progress OS spawn until it returns. Split requests that exceed admission.

V1–V3 models, identities, PCM and archive bytes remain unchanged. Other sample
formats, channel conversion, dither and scene/location schedules remain unsupported.
