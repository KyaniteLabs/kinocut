# Pre/post-fader bus sends

V2/V3 supplied mixes can render `plan.routing.sends` using the existing
`SendReturn` contract. Add a directed send to an otherwise valid
[routed request](SOUND_ROUTING_REQUESTS.md):

```json
{
  "sends": [
    {
      "send_id": "voice-return",
      "source_bus_id": "dialogue",
      "destination_bus_id": "ambience",
      "gain_db": -6,
      "post_fader": true
    }
  ]
}
```

This fragment belongs inside `plan.routing`. Both buses must be declared and
match delivery stems. Send IDs must be unique. Distinct IDs may deliberately
connect the same pair of buses; each contributes separately. Self-sends and
longer cycles are rejected, regardless of gain. Feedback/delay routing is not
implemented. Raw gains must be actual finite numbers and `post_fader` an actual
boolean; typed model state is revalidated. The existing default is post-fader.

## Signal order

Track processing and automation precede placement/crossfades. The optional bed
and explicit layers/ducking are assembled next. Sends process those bus canvases
before final stem encoding and recombination.

Each bus receives all incoming returns before its own gain is applied once:

```mermaid
flowchart LR
  Direct[Direct bus audio] --> Sum[Add incoming returns]
  Sum --> Pre[Pre-fader tap]
  Pre --> Gain[Bus gain]
  Gain --> Post[Post-fader tap and retained stem]
  Pre -->|post_fader false| Send[Send gain]
  Post -->|post_fader true| Send
  Send --> Destination[Destination input before its gain]
```

A pre-fader send reads the complete source bus, including earlier returns,
before source-bus gain. A post-fader send reads after that gain. Chained sends
therefore carry transitive returns. Incoming returns are accumulated in the
original `Routing.sends` tuple order; independent ready buses use lexical
topological order. Reordering sends can change PCM when positive and negative
contributions saturate. Parallel contributions are never deduplicated.

Send gain uses `10**(gain_db/20)`, ties-to-even rounding and PCM16 saturation,
followed by the mixer's existing per-addition destination saturation. Source-bus,
send and destination gains are separate stages; their intermediate clipping is
observable. Both stereo channels use the same send gain, without crossfeed or
conversion. Bus `kind` is descriptive: sends do not invent reverb or another effect.

Layer ducking finishes before send processing. Its detector excludes send returns,
which prevents implicit control feedback. Send-bearing layer-duck receipts
identify that tap as `after_clips_before_sends_and_bus_gain`. Track automation
still affects the audio entering the bus graph. [Final bus sidechains](SOUND_SIDECHAIN_REQUESTS.md)
run after returns and bus gains; sends keep their pre-sidechain signals.

## Evidence and limits

Send-bearing receipts use routing algorithm `sent_pcm16_ties_even_v1`, retaining
the underlying `track_algorithm` and any automation section. The `sends` section
uses `acyclic_bus_sends_v1` and records ordered descriptors, factors, pre/post taps,
topological order, pre-fader source IDs, frame shape and signal-order policy.
Public results add `send_count` and `sends_sha256`; `routing_sha256` covers all
routing evidence. Existing receipt schemas remain for newly accepted send states.
All successful no-send request hashes, audio and archives are unchanged.

The processor holds one read-only PCM snapshot per distinct pre-fader source,
shared by its parallel edges. Post-fader source views are also read-only, and
completed source buses are not modified again. This is internal processor
ownership, not kernel-immutable input protection. No full-duration buffer is
allocated per send. Aliased or mismatched direct-core bus buffers are rejected.

Limits: 64 sends, 8 buses, 128 KiB send evidence, 1 MiB routing evidence and 2 MiB
whole receipt. Rounded output frame count must be positive. Snapshot memory
`2 * frames * channels * pre_fader_sources` plus 1 MiB graph metadata is added to
existing admission, within the same 2 GiB estimate.

Send work is capped at 128 million structural units:
`frames * channels * (stems + 2*sends + pre_fader_sources) + stems + sends`.
Combined send, automation and layer fill/duck work is capped at 256 million,
while existing individual automation and layer-duck limits remain. Worker
preflight checks actual selected windows/layer shapes before per-frame rendering;
the parent recomputes the combined bound from independently verified windows and
layer shapes. Ordinary bed, codec and IO limits are separate. These are admission
policies, not measured RSS or speed promises; the worker deadline remains independent.

The parent verifies graph metadata and structural bounds against the request.
It does not independently re-render acoustic send effects. Exact PCM tests cover
the processor; human listening and mastering remain separate acceptance steps.
Filesystem, cancellation and no-overwrite publication rules are unchanged.
