# Final bus ducking sidechains

V2/V3 supplied mixes execute `plan.routing.sidechains` after all send returns and
bus faders. The existing `DuckingSidechain` contract names source/target buses and
attenuation, attack, release and recovery:

```json
{
  "sidechains": [
    {
      "source_bus_id": "dialogue",
      "target_bus_id": "ambience",
      "attenuation_db": 9,
      "attack_ms": 80,
      "release_ms": 350,
      "recovery_ms": 500
    }
  ]
}
```

This fragment belongs inside `plan.routing` of a valid routed request. Both buses
must exist and differ. Duplicate source/target pairs are rejected. Raw numeric
fields must be actual finite numbers excluding booleans; malformed typed state
is revalidated. Recovery must be at least release. Use the existing Python, CLI
or MCP `sound_mix_render` path; no new tool name or request version is required.

## Fixed detector signals

Tracks/automation, placement/crossfades, bed/layers/early layer ducking, send returns
and bus gains finish first. The processor then snapshots every distinct detector
bus before applying any final bus sidechain. Detectors therefore see
`after_sends_and_bus_gain_before_sidechains` signals, and targets are complete bus
stems. Source-bus fader changes can affect detection.

All controllers use those fixed snapshots. Two-way controls such as A-to-B and
B-to-A are deterministic and do not iterate feedback. Data-send cycles still
fail. Different sources may target the same bus; their gains compound in declared
controller order with PCM16 rounding after each stage. Sends retain their earlier
pre-sidechain values and are not recomputed after final ducking.

Layer ducking is a separate earlier effect with its pre-send/pre-fader detector.
Both can be explicitly requested and are reported separately. No controller is
silently deduplicated or substituted for another effect.

The shared linked envelope detects maximum absolute channel level strictly above
0.02 of full scale and applies one gain across stereo target channels. Timing is
rounded upward to whole frames; ramps restart from current gain and reach exact
attack/release endpoints. Samples round ties-to-even and saturate PCM16. Recovery
is a deadline, not an extra processing phase. Completed releases, final truncated
recovery and `not_exercised` cases use the same rules as
[layer ducking](SOUND_LAYER_REQUESTS.md#explicit-layer-ducking).

## Evidence

Routing evidence uses `sidechain_pcm16_ties_even_v1`, retains the inner routing
algorithm and automation/send sections, and adds deterministic `sidechains`
metadata under `linked_bus_sidechains_v1`: ordered contracts, snapshot-source IDs,
frame parameters, detector/target scope and controller order.

Actual envelope summaries are separate in the top-level
`bus_sidechain_measurements` list. Each ordered entry identifies its source and
target and records active frames/runs, minimum/final gain, completed releases,
maximum release frames, final detector activity and truncated recovery. A recovery
`pass` for earlier completed releases may coexist with a truncated final release;
inspect both fields. No completed release is `not_exercised`.

Public results add `sidechain_count`, `sidechains_sha256` over deterministic
routing-sidechain metadata, and `sidechain_measurements_sha256` over the canonical
mapping `{"measurements": bus_sidechain_measurements}`. The full routing hash
remains deterministic. No-sidechain schema numbers, request hashes, PCM and
archive bytes remain unchanged.

The parent checks controller identities/cardinality, strict summary types and
relationships, routing metadata and resource bounds. It does not independently
re-render or prove acoustic effects from those summaries. Results are prepared
before exclusive publication, so metadata-formatting failures do not commit an
output. Human listening and mastering remain separate acceptance steps.

## Limits and ownership

Limits: 64 controllers, existing 8 buses, 128 KiB sidechain metadata and measured
summary list, 1 MiB routing evidence and 2 MiB whole receipt. Rounded output frames
must be positive. Distinct owned PCM16 target buffers are checked before mutation;
one read-only snapshot is shared per detector source. This is processor ownership,
not kernel-immutable input protection.

For F output frames, C channels, N controllers and K unique detector sources,
sidechain work is `F*C*(2*N+K)+N+K`, capped at 64 million structural units.
The existing 256-million combined routed-feature cap includes this work alongside
sends, automation and layer fill/ducking, with individual limits retained.
Memory admission adds `2*F*C*K` snapshot bytes and 1 MiB metadata to existing
allowances under the same 2 GiB estimate. Send and sidechain snapshot allowances
are summed conservatively. No full target or envelope buffer is allocated per
controller. These are admission policies, not measured speed/RSS promises.
Existing worker deadlines, safe source reads, cancellation and no-overwrite
publication remain in effect.
