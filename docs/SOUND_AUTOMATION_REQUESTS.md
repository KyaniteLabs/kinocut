# Track gain and pan automation

Supplied mix requests V2 and V3 can render `plan.routing.envelopes` for named
tracks. Add envelopes to an otherwise valid [routed request](SOUND_ROUTING_REQUESTS.md):

```json
{
  "envelopes": [
    {
      "target_track_id": "voice",
      "parameter": "gain_db",
      "points": [
        {"time_seconds": 0, "value": -6},
        {"time_seconds": 2, "value": 0}
      ]
    }
  ]
}
```

This fragment belongs inside `plan.routing`; `voice` must be a declared, bound
track and the two-second point must fit the timeline. Use the same Python
`sound_mix_render`, CLI `sound mix-render` or MCP `sound_mix_render` operation.
The typed contracts remain `AutomationEnvelope` and `AutomationPoint`.

Only `gain_db` and `pan_position` are supported. Values use existing gain/pan
bounds; pan positions range from -1 to 1. Each track can have at most one envelope
per parameter. Unknown targets, duplicate parameters, boolean/nonfinite values
and malformed typed state fail validation. Existing numeric-model compatibility
applies to points; a boolean cannot stand in for a number.

## Clock and parameter meaning

Envelope values are absolute parameter values, replacing the corresponding static
track setting. They are not offsets. The other parameter retains its static
setting. Pan law and mute/solo remain static; mute/solo always wins. Mono still
requires centered linear pan, including zero values throughout any pan envelope.

Times refer to the global output timeline. Each point is quantized with
`round(time_seconds * sample_rate_hz)`, using ties-to-even. Points must occupy
distinct increasing frames within `0..frame_count`, inclusive. Two different
times that round to the same frame are rejected. The end boundary is frame
`frame_count`; the last emitted sample is at `frame_count - 1`.

Values interpolate linearly in their own units: dB for gain, position for pan.
The exact point value applies at its quantized frame. Before the first point,
the first value is held; after the last, the last value is held. A single point
sets a constant value throughout. The static setting is not used before the first
point of an enveloped parameter; declare an initial point at zero when needed.

Selected source frame zero maps to its cue's rounded timeline start. A source
in-point changes which media is selected, not the automation clock. Multiple
cues on the same track therefore share global automation time. Outgoing post-roll
and incoming material are independently automated at matching global times before
the existing crossfade blend. The mixer retains its exact rounded adjacency
guard, cue positions, source windows and tail.

Each frame combines the current gain and pan into one channel factor, then rounds
ties-to-even and saturates PCM16 once per sample. Existing pan laws apply without
crossfeed or channel conversion. Automation precedes clip placement/crossfades,
the optional bed, explicit layers/ducking and final bus gain. Layer ducking can
therefore detect the automated source, while source-bus gain still follows detection.
Automation does not apply to the separate bed, buses, layer descriptors or effects.

## Evidence and resource limits

Requests with envelopes use routing algorithm `automated_pcm16_ties_even_v1` and
an `automation` section with `global_linear_parameters_v1`, clock/interpolation/
endpoint policy and normalized points with quantized frames. Cue binding evidence
includes global start frames. Automated track entries identify each parameter as
coming from the envelope or static track; they do not claim constant applied
channel factors. Unautomated tracks retain their actual constant factors.

The compact result adds `automation_envelope_count`, `automation_point_count` and
`automation_sha256`. `routing_sha256` covers all routing evidence. Existing receipt
schema numbers remain for these newly accepted request states. Empty-envelope
V1/V2/V3 request hashes, audio and archives are unchanged. Receipt envelopes are
sorted by track/parameter, but existing SoundPlan tuple-order identity remains:
reordering declarations can change request hashes even when PCM is equivalent.

Before publication, the parent independently re-reads and hash-checks automated
clip sources, validates their formats, derives selected windows using the same
bound rules, compares receipt windows and recomputes work admission. Changed
sources fail closed. Async cancellation is observed between bounded source reads
and before publication; individual synchronous reads/decodes are not interruptible
by that cooperative boundary. Source-shape verification is shared with layers.
The parent does not independently re-render automation or prove acoustic effects
from receipt metadata; exact PCM tests establish processor behavior.

Limits: 512 envelopes, 4,096 points per envelope, 8,192 points total, 1 MiB request,
1 MiB routing evidence and 2 MiB whole receipt. Normalized routing evidence is
bounded during admission. Automated requests reserve an extra 32 MiB for point,
cursor, receipt and parent-proof metadata within the existing 2 GiB estimate.
They do not allocate full-duration gain arrays or per-track timeline canvases.

The 64-million structural work-unit cap includes compilation (`points + envelopes`)
plus, for each automated selected clip, `frames * channels * (1 + E)` and
`sum(P + P.bit_length() + 1)` over that track's envelopes. `E` is the per-track
envelope count and `P` each envelope's point count. Inactive tracks and repeated
bindings are charged conservatively. This covers cursor work even for tiny clips
with many points. Actual selected-source shapes are checked before per-frame
processing or target-canvas allocation, and the parent recomputes the same bound.
These are admission policies, not measured RSS or speed guarantees. The existing
worker deadline remains independent.

V2/V3 automation can compose with [finite bus sends](SOUND_SEND_REQUESTS.md).
V1 still requires default routing. General sidechains, other automation
parameters, bus automation, nondefault latency and unsupported formats remain
rejected. Mix output remains an assembly; mastering and human listening are
separate acceptance steps.
