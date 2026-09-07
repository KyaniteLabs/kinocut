# Measured sound loudness

The separate Python `LoudnessAdapter` preserves normalized gain and compensates
limiter lookahead, including the final audio tail. Its `PostStageResult.metrics`
are requested targets, not measured compliance. Single-pass normalization can
still miss the target on transient-heavy material; measure the final output with
this QA operation before accepting it. Successful processing alone is insufficient.

`sound_qa_loudness` analyzes unchanged local mono PCM16 WAV audio with an installed
FFmpeg `ebur128` meter. It reports integrated loudness, reconstructed true peak,
loudness range and actual delivery-policy compliance. Missing FFmpeg or its filter
is an explicit error; there is no proxy-meter fallback.

Use the same request with Python, CLI or MCP:

```json
{
  "schema_version": 1,
  "source": {"path": "master.wav", "sha256": "sha256:<actual lowercase digest>"},
  "delivery": {}
}
```

```python
from kinocut import Client

report = Client().sound_qa_loudness(request=request, project_root="/your/project")
assert report["within_tolerance"]
```

```sh
kino --format json sound-qa-loudness --request-json request.json --project-root .
```

MCP accepts `request` and `project_root`. Python also accepts `wav_bytes` with an
optional `delivery` policy. Bytes and request modes cannot be combined. Unknown
fields, explicit empty audio, changed hashes, symlinks and unsafe paths fail.
Source reads follow the [public mixing filesystem policy](SOUND_MIX_REQUESTS.md).

The report binds source SHA256, policy hash and FFmpeg version. It contains no
source paths or raw diagnostics. No media output is published; private analysis
files are removed after the child is reaped.

Processing success is distinct from compliance: valid noncompliant audio returns
`within_tolerance=false`, including in a successful CLI/MCP inspection response.
`kinocut_sound.qa.check_loudness` is the strict Python gate and raises
`qa_loudness_fail` for a violation. Integrated loudness must satisfy the policy's
tolerance; true peak must satisfy the stricter of its two peak ceilings. LRA is
measured, but the policy currently defines no LRA pass threshold.

Omitting inputs runs a labelled `demo=true` fixture through the real meter. Its
compliance is measured. This operation does not normalize audio, certify
perceptual quality, run ASR or replace human listening.

## Bounds and measurement validity

Inputs are at most 256 MiB, 8–96 kHz and one hour. Material must contain nonzero
samples and last at least 3 seconds. Undefined/nonfinite results and integrated
results at or below -70 LUFS fail as `qa_unmeasurable`. Zero LRA is valid. The
3-second admission floor does not establish representative programme statistics
for every short clip.

The meter deadline is 60 seconds; its version probe allows 2 seconds. Combined
diagnostics are consumed in 4096-byte chunks with a 64 KiB retained limit.
Overflow terminates the child while it runs. Timeout, interruption and repeated
async cancellation retain ownership through pipe draining and reaping. These
bounds do not claim protection against a hostile backend spawning descendants.

Calibration covers a known-level 1 kHz tone, a programme with 20 LU level range,
and a waveform whose reconstructed peak exceeds its sample peak by about 3 dB.
See [FFmpeg's meter documentation](https://ffmpeg.org/ffmpeg-filters.html#ebur128).
