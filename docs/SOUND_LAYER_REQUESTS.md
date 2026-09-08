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

Non-null `layer_ducking` is rejected until its source/target/recovery semantics
are implemented. Scene/location schedules, routing sends, automation, sidechains,
format conversion and dither also remain unsupported. This produces an assembly,
not verified mastering; human listening and episode acceptance remain required.
