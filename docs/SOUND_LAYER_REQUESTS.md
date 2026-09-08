# Supplied ambient layers

Mix request version `3` adds real ambient-layer rendering to the existing static
routing request. Use `kinocut_sound.public.SoundMixRequestV3` and `LayerAsset`, or
send the same JSON through Python `sound_mix_render`, CLI `sound mix-render`, or
MCP `sound_mix_render`. The [V2 routing fields](SOUND_ROUTING_REQUESTS.md) remain
required. V1/V2 shapes, request hashes and archive bytes are unchanged.

Add `layer_assets` to a V2 request and set `schema_version` to integer `3`:

```json
{
  "layer_assets": [
    {
      "layer": {
        "layer_id": "wind",
        "asset_ref": "wind-recording",
        "gain_db": 0,
        "muted": false,
        "soloed": false
      },
      "source": {"path": "audio/wind.wav", "sha256": "sha256:<actual-file-digest>"},
      "fill_mode": "loop",
      "crossfade_frames": 2205
    }
  ]
}
```

This fragment supplements the complete request; replace the digest with the
actual file hash. `plan.layers` must equal the ordered layer IDs, here `["wind"]`.
The source must match the plan's PCM16 mono/stereo layout and sample rate. There
must be an `ambience` stem and routing bus. A silence-only timeline can supply
the duration with empty clips, tracks and cue bindings.

Layer IDs are unique. `asset_ref` is an identity, never a file path. Reusing one
asset reference requires the same path/hash binding. Multiple explicit layers
may intentionally use the same source; each contributes separately. Gain must
be an actual finite number, flags actual booleans, and crossfade frames an actual
positive integer. Typed request state is revalidated at public admission.

## Fill and gain

Every layer starts at frame zero and fills the authoritative timeline, including
its declared tail. The target is `round(duration * sample_rate)` and must contain
at least one frame.

- `pad`: set `crossfade_frames` to `null` or omit it. Longer sources are trimmed;
  shorter sources are followed by exact zeros. There is no automatic repetition.
- `loop`: supply `1 <= crossfade_frames < source_frames`, including when the
  first copy already covers the target. The step is `source_frames-crossfade_frames`.
  The renderer uses the minimum number of copies covering the target, then trims.

At each repeat, the first C frames blend the existing layer canvas with incoming
source using incoming weight `(j+1)/C`, for `j=0..C-1`. The final overlap frame is
fully incoming. Later frames use incoming samples directly. Repeats are processed
in order, including crossfades wider than half the source. One crossfade frame is
a one-frame switch; arbitrary recordings are not guaranteed to sound seamless.

Mute wins over solo. If any layer is soloed, only soloed, unmuted layers contribute.
Inactive layers contribute exact silence, while their source files are still
opened, hash-checked and validated. Each active source is scaled by
`10**(gain_db/20)` before fill, with ties-to-even rounding and PCM16 saturation.
Crossfade blends use the same rounding and saturation, with linked stereo weights.

Layers accumulate in declared order after existing clips and the optional bed,
using the mixer's existing per-addition saturation. Routing bus gain is applied
after all layers. `duck_bed` affects only the separately declared `bed`, before
layers are added. V3 applies no extra legacy `LayerStack.bus_gain_db()` gain.

## Evidence and limits

The ZIP receipt uses schema `4`, request schema `3`, explicit channel/frame counts,
the static routing section, and an ordered `layers` section. Each entry retains
its descriptor, source binding, audibility, applied gain factor, fill mode and
measured frame plan. Loop evidence includes source/target frames, step, copies
and last seam bounds rather than an unbounded seam list. The algorithm is
`ambient_pcm16_sequential_crossfade_v1`.

Public results add `layer_count`, `layer_algorithm` and `layers_sha256`; full details
remain in `receipt.json`. Before publication the parent independently re-reads
and hash-checks layer sources, decodes their actual shapes and checks receipt
claims. A changed source fails closed. Async verification observes cancellation
between source reads and before publication; an individual bounded synchronous
read/decode is not interruptible by that cooperative cancellation.

Limits: 64 layers, 10,000 extra loop copies, 256 MiB total explicit source bytes,
1 MiB request, 1 MiB layer section and 2 MiB whole receipt. Duplicate bindings
count toward the cumulative source budget. Admission includes source buffers,
one layer scratch canvas, stems and receipt overhead under the existing 2 GiB
memory estimate. The worker retains its 300-second deadline. These are admission
bounds, not measured host peak requirements.

Scene/location schedules, feedback send cycles, unsupported automation parameters,
other sample formats, channel conversion and dither remain unsupported. V4 can
normalize layer rates through [explicit source resampling](SOUND_RATE_CONVERSION.md)
before the same fill/ducking rules. This produces an assembly,
not verified mastering; human listening and episode acceptance remain required.
Bound tracks can use [gain/pan automation](SOUND_AUTOMATION_REQUESTS.md); layer
descriptors themselves are not track-automation targets.

## Explicit layer ducking

V3 may include one `layer_ducking` contract when at least one layer is present:

```json
{
  "layer_ducking": {
    "source_bus_id": "dialogue",
    "target_bus_id": "ambience",
    "attenuation_db": 9,
    "attack_ms": 80,
    "release_ms": 350,
    "recovery_ms": 500
  }
}
```

The target must be `ambience`; the source must be a different declared bus.
The source can be dialogue, SFX or another declared stem. Detection uses the
maximum absolute channel level before bus gain, with activity strictly above
0.02 of full scale. Both stereo layer channels share the same envelope.
Source-bus gain therefore does not change detection. Ducking occurs after layer
gain and fill, before [bus sends](SOUND_SEND_REQUESTS.md), layer accumulation and
target-bus gain. Send returns are not part of the layer detector.
It affects only
explicit layers; ambience clips and the optional bed retain their own behavior.
`duck_bed` can operate independently at the same time. [Final bus sidechains](SOUND_SIDECHAIN_REQUESTS.md)
can also be requested as a separate later effect; their detectors see completed
send returns and bus faders rather than the layer detector's earlier tap.

Attack, release and recovery are rounded upward to whole frames. Gain starts at
one; each activity transition starts a linear ramp from the current gain to the
attenuated or unity target. The ramp reaches its exact target after the declared
attack/release frames. Interrupted ramps restart from their current gain.
Samples use ties-to-even rounding and PCM16 saturation. The separate legacy bed
ducker is unchanged.

`recovery_ms` is a deadline for returning to unity, not another processing phase;
it must be at least `release_ms`. Recovery can complete only when the timeline
contains enough uninterrupted inactive frames. The receipt records completed
releases and a final truncated-release count/flag. `recovery_status` is `pass`
when completed releases were observed within the deadline, or `not_exercised`
when none completed. A `pass` for earlier completed releases can coexist with a
truncated final recovery, so inspect both fields before accepting an episode.

The existing receipt schema stays `4`, request schema `3`. A ducked request adds
`layers.ducking` with algorithm `linked_layer_ducking_v1`, the contract, detector
semantics, quantized frame settings and measured summary. Summary fields include
active frames/runs, minimum/final gain, completed releases, maximum completed
release frames, final detector activity and truncated recovery. Public results
add `layer_ducking_sha256`; `layers_sha256` covers the complete layer section.
Requests with `layer_ducking: null` or omitted retain their previous bytes/hashes.

The parent independently verifies source identities/shapes and structural work
counts, and checks summary types, ranges and relationships. It does not re-render
the detector to independently prove the worker's acoustic measurements. Exact
PCM tests verify the processor; listening remains a separate acceptance step.

Ducked requests also have a 64-million sample-visit work ceiling. Admission counts
source processing, worst-case loop writes, scratch/overlay and detector/envelope
passes before rendering. Inactive sources and an all-inactive detector pass still
count. Long layers, many layers or very wide loop overlaps may exceed this limit.
This structural ceiling is not a measured speed guarantee; the worker's existing
deadline remains a separate limit. No-duck admission remains unchanged.
