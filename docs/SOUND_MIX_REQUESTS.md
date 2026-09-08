# Mix supplied audio

`sound_mix_render` accepts a persisted `SoundMixRequest` and an explicit local
project root. It assembles supplied mono or stereo PCM16 WAVs into a new ZIP containing
`master.wav`, `stems/<id>.wav`, and `receipt.json`. It does not synthesize speech
or apply loudness mastering. The receipt reports `mastering_status=not_applied`
and requires human review.

The same request works in Python, CLI and MCP:

```python
import json
from kinocut import Client

request = json.loads(open("request.json", encoding="utf-8").read())
result = Client().sound_mix_render(request=request, project_root=".")
print(result["output_path"], result["output_sha256"])
```

```sh
kino --format json sound-mix-render --request-json request.json --project-root .
```

For MCP call `sound_mix_render` with `request` (the JSON object) and
`project_root`. Omitting both arguments preserves the small smoke test, with
`demo: true`. An invalid or empty explicit request never falls back to that demo.

## Request contract

`kinocut_sound.public.mix_request.SoundMixRequest` supplies the validated schema.
Its `schema_version` is integer `1` and unknown fields are rejected.

| Field | Meaning |
|---|---|
| `plan` | Existing serialized `SoundPlan`; its identity rules are unchanged |
| `clips` | Array of `{cue_id, path, sha256, stem_id}` bindings for every audible cue |
| `transitions` | Optional `{outgoing_cue_id, incoming_cue_id, duration_seconds}` crossfades |
| `bed` | Optional `{path, sha256}` matching the plan's sole bed reference |
| `duck_bed` | Boolean, default false; requires a bed and a declared dialogue stem |
| `output_path` | New project-relative ZIP filename; parent directories must exist |

Asset hashes use `sha256:<lowercase hex>`. A clip path must equal its cue's
`source_ref`; each audible cue has exactly one binding. Silence and chapter
markers have no clip binding. Stems must be declared by the delivery layout;
an empty layout selects dialogue, ambience and sfx. A bed requires a declared
ambience stem. Ambience clips and the separate bed are added together with
PCM16 saturation. Ducking affects only the bed, preserving the ambience clips.

Crossfades use actual outgoing post-roll and preserve incoming cue timing, as
described in [Sound crossfades](SOUND_CROSSFADES.md). Persisting a crossfade in
the request binds it to request identity without changing existing plan hashes.
Relative destination and source hashes are identity-bearing; the host project
root is not. The archive receipt hashes media members; the response separately
hashes the complete ZIP, avoiding a circular hash.

## Current rendering capabilities

Assembly supports mono or stereo signed 16-bit PCM, a shared sample rate from 8–96 kHz,
continuous time, explicit silence/tail, named stems, source windows and post-roll
crossfades. Cue `in_point_seconds` is inclusive (default zero), while
`out_point_seconds` is exclusive (default source end). Seconds quantize with
`round(seconds * sample_rate_hz)`. Out-of-range seconds and empty quantized
windows fail instead of clamping. Silence and chapter markers cannot select
source windows. Several cues may select different windows of one source file.

Selected samples are prepared once before crossfades and placement. Short
selections are padded with silence to the cue duration; longer ones are truncated
to that duration. Crossfades require actual post-roll inside the selected window,
including its out-point. The receipt's `source_windows` records cue ID, in/out
sample positions, selected count and rate; source hashes still bind the original
whole file. These fields preserve existing SoundPlan identity semantics.

Every clip and bed must match the plan's channel count and sample rate. There is
no implicit channel conversion or resampling. Stereo trims and crossfades use
frames; both channels receive the same fade gain. Ducking detects the larger
absolute speech channel and applies one shared gain to both bed channels, so
opposite-polarity speech cannot cancel the detector. Stem addition preserves
insertion order and clamps each PCM16 addition.

Mono receipts retain schema version 1 and byte-compatible fields. Stereo
receipts use schema version 2 and add `frame_count`, `channel_count` and
`interleaved_sample_count`; the legacy `sample_count` is an alias for frame count.
Stereo source windows use `in_frame`, `out_frame`, `frame_count`, `channel_count`,
`interleaved_sample_count`, `sample_rate_hz` and `cue_id`. Estimated working memory
includes both channels. Loudness inspection and mastering accept stereo mixes;
ASR still requires mono inputs.

Assembly rejects `transit_kind`, nondefault routing, layers, format
conversion and dither until those rendering paths are implemented. It does not
silently discard those requests. Declared delivery targets are retained as plan
intent, not reported as achieved mastering. Full episode listening and complete
sonic-world rendering remain separate acceptance work.

Request limits are 1 MiB and 32 levels of JSON nesting, with at most 4096
clips/cues, 256 MiB total source bytes, eight stems, one hour and a conservative
2 GiB estimated render-memory ceiling. These limits are cumulative: a request
below one ceiling can still exceed another. The worker has a 300-second deadline.

## Filesystem and cancellation

This supplied-media path requires descriptor-relative no-follow reads and
exclusive hardlink publication, available on supported macOS/Linux filesystems.
Unsupported hosts fail with `mix_platform_unavailable` before writing. Windows
does not gain this supplied-media capability from the existing smoke demo.
Paths must be project-relative and cannot traverse symlinks or parent directories.
Inputs must be regular files and match their hashes; no network is used.

Publication creates a new ZIP and never overwrites an existing file, directory,
or symlink. Rendering stages privately next to the destination. Cancellation or
failure before the exclusive final link removes owned staging and leaves no
final artifact. Once that link succeeds, the ZIP is complete; interruption can
prevent the caller receiving its response without invalidating the artifact.
A retry returns `mix_output_conflict` and preserves the existing output.

MCP cancellation terminates and reaps its rendering worker. These protections
cover hostile request paths and normal cancellation, not a malicious process
with the same OS authority that renames held directories, or cleanup after the
operating system forcibly kills the parent. Never interpret a file's presence
alone as acceptance: inspect its receipt, hashes and decoded media.
