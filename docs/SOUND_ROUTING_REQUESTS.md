# Static track and bus routing

Mix request version2 adds explicit cue-to-track bindings. It renders static track
gain, mono/stereo pan, mute/solo and destination-bus gain through the same Python,
CLI and MCP operations as [version1 supplied mixing](SOUND_MIX_REQUESTS.md).
Version1 request fields, hashes and archive bytes remain unchanged.

Start with a valid supplied-media request and choose a new output path:

```python
import json
from pathlib import Path
from kinocut import Client
from kinocut_sound.public.mix_request import load_mix_request

request = load_mix_request(
    json.loads(Path("mix-request.json").read_text(encoding="utf-8"))
).model_dump(mode="json")
request["schema_version"] = 2
request["output_path"] = "routed.zip"
stems = request["plan"]["delivery"]["stems"]["stem_ids"] or ["dialogue", "ambience", "sfx"]
stereo = request["plan"]["format"]["channel_layout"] == "stereo"
request["cue_tracks"] = [
    {"cue_id": clip["cue_id"], "track_id": f"track-{index}"}
    for index, clip in enumerate(request["clips"])
]
request["plan"]["routing"] = {
    "tracks": [
        {"track_id": f"track-{index}", "destination_bus_id": clip["stem_id"],
         "gain_db": -3.0, "pan_law": "balanced" if stereo else "linear",
         "pan_position": 0.0, "muted": False, "soloed": False}
        for index, clip in enumerate(request["clips"])
    ],
    "buses": [{"bus_id": name, "kind": name, "gain_db": 0.0, "pan_law": "linear"} for name in stems],
}
result = Client().sound_mix_render(request=request, project_root=".")
print(result["output_path"], result["routing_sha256"])
```

The typed constructor is `kinocut_sound.public.SoundMixRequestV2`, with
`CueTrackBinding` entries. JSON versions must be actual integers; booleans,
strings and floating-point versions fail. Raw routing flags must be actual
booleans and gain/pan values actual numbers. Already-constructed models are
validated from their current serialized state; this cannot recover values an
earlier constructor already coerced. Malformed `model_copy` states fail on load.

Every audible cue binds exactly once. Several cues can share a track, but every
declared track must be used. A track's destination bus must equal each bound
clip's `stem_id`, and buses must match the selected delivery stems. Bus `kind`
is descriptive metadata, not an effects selector. Silent and chapter cues have
no track binding. A `BED` cue is audible and requires a normal binding. The
separate optional `bed` is added once to ambience without a cue binding; declaring
both contributions deliberately adds both, even when they reference identical bytes.

## Signal order and pan

Processing order is source-window selection, track gain/pan and mute/solo,
crossfades, placement, optional bed/ducking, bus gain, then stem recombination.
Existing crossfades require two LINE cues on the same stem. Muting retains zero
PCM for the original duration. When any track is soloed, only soloed and unmuted
tracks contribute; otherwise every unmuted track contributes.

Stereo pan scales existing left/right independently, with no crossfeed or channel
conversion. For position `p` from −1 to 1:

| Law | Left scale | Right scale | Center |
|---|---|---|---|
| `linear` | `(1-p)/2` | `(1+p)/2` | 0.5 per channel |
| `constant_power` | `cos((p+1)*pi/4)` | `sin((p+1)*pi/4)` | approximately 0.707 per channel |
| `balanced` | `min(1,1-p)` | `min(1,1+p)` | unity |

Mono requires centered `linear` pan and uses unity pan scale. Each sample uses
one factor `10**(gain_db/20) * pan_scale`, Python ties-to-even rounding, then
PCM16 saturation. Existing per-addition saturation and accumulation order remain.
Bus gain rounds and clamps once after all contributions to that stem, including
its optional bed. Gains can clip; this operation is not loudness mastering.

## Evidence and limits

Version2 archives retain receipt schema3 with `request_schema_version: 2`, explicit
frame/channel/interleaved counts and a `routing` section. Routing evidence contains
canonical cue-track bindings, applied track states/factors and bus gains under
algorithm `static_pcm16_ties_even_v1`. It contains no audio paths; existing
project-relative source/bed metadata remains elsewhere in the receipt. The parent
verifies routed metadata against the request before publishing.

Responses keep the routing summary compact: `routing_algorithm`, `routing_sha256`
and `routed_cue_count`. Inspect `receipt.json` for the full routing evidence.
Cue-track binding order is canonicalized for hashing, while existing SoundPlan
track/bus identity rules remain. Bit-for-bit cross-platform libm parity is not promised.

Limits are 256 tracks, 8 buses, 4,096 bindings, 1 MiB requests, 1 MiB encoded routing evidence
and 2 MiB total receipt. V2 memory admission includes transformed sources, timeline
buffers and receipt preparation under the existing 2 GiB estimate. The worker has
the existing 300-second deadline. Filesystem, cancellation and no-overwrite
publication rules are unchanged.

Sends, sidechains, automation envelopes, nondefault latency, non-linear bus pan,
layers, format conversion and unsupported sample layouts remain rejected. These
requests never silently drop their unimplemented intent.
